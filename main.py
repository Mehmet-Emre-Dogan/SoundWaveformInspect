#!/usr/bin/python3
import pyaudiowpatch as pyaudio
from utilityFunctions import LoadConfig
from constants import *
from guiFiles.mainGui import Ui_MainWindow as mainMainWindow
import sys
import os
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtWidgets import QMainWindow, QApplication
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
import time

if os.name == 'nt':  # Only if we are running on Windows
    from ctypes import windll
    k = windll.kernel32
    k.SetConsoleMode(k.GetStdHandle(-11), 7)

class SoundCapturer(QThread):
    sigBlockCaptured = pyqtSignal(bool)
    sigFFTDataReady  = pyqtSignal(np.ndarray, np.ndarray)  # Signal for FFT data

    def __init__(self, p_dtConfigDict):
        super(SoundCapturer, self).__init__()
        self.dtConfig = p_dtConfigDict

        self.leftArrayData  = []
        self.rightArrayData = []

        self.blRun          = True

        with pyaudio.PyAudio() as p:
            try:
                # Get default WASAPI info
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            except OSError:
                print("WASAPI is not available on the system. Exiting...")
                exit()

            if self.dtConfig["UseSpeakerOrMic"] == "Speaker":
                default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                
                if not default_speakers["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break
                    else:
                        print("Default loopback output device not found. Exiting...")
                        exit()

                self.NumberofChannels = default_speakers["maxInputChannels"]
                self.iRate = int(default_speakers["defaultSampleRate"])
                self.iInputFramesPerBlock = int(self.iRate * self.dtConfig["InputBlockTimeInSeconds"])
                self.iInputDeviceIndex = default_speakers["index"]

            elif self.dtConfig["UseSpeakerOrMic"] == "Mic":
                default_microphones = p.get_device_info_by_index(wasapi_info["defaultInputDevice"])

                self.NumberofChannels = default_microphones["maxInputChannels"]
                self.iRate = int(default_microphones["defaultSampleRate"])
                self.iInputFramesPerBlock = int(self.iRate * self.dtConfig["InputBlockTimeInSeconds"])
                self.iInputDeviceIndex = default_microphones["index"]

                print(self.iRate)

            else:
                raise Exception("Invalid <UseSpeakerOrMic> param. Use 'Speaker' or 'Mic'")

    def run(self):
        with pyaudio.PyAudio() as p:
            with p.open(format=pyaudio.paInt16,
                        channels=self.NumberofChannels,
                        rate=self.iRate,
                        input=True,
                        frames_per_buffer=self.iInputFramesPerBlock,
                        input_device_index=self.iInputDeviceIndex
                        ) as stream:

                while True:
                    data = stream.read(self.iInputFramesPerBlock, exception_on_overflow=False)
                    arrayData = np.frombuffer(data, dtype=np.int16)
                    self.leftArrayData = arrayData[0::2]
                    self.rightArrayData = arrayData[1::2]

                    if self.blRun:
                        if self.dtConfig["TimeDomainScopeEnabled"]:
                            # Emit signal for time domain plot
                            self.sigBlockCaptured.emit(True)

                        if self.dtConfig["FrequencyDomainScopeEnabled"] or self.dtConfig["FFTSpectrumVisualizerEnabled"]:
                            # Calculate FFT and emit signal
                            self.perform_fft(self.leftArrayData)  # Send left channel data for FFT

    def perform_fft(self, data):
        N = len(data)
        fft_data = np.fft.fft(data)
        fft_data = np.abs(fft_data[:N // 2])

        # Normalize FFT magnitude by dividing by N
        fft_data = np.abs(fft_data[:N // 2]) * (2.0 / N)

        frequencies = np.fft.fftfreq(N, 1 / self.iRate)[:N // 2]
        self.sigFFTDataReady.emit(frequencies, fft_data)

class FFTScope(QMainWindow):
    def __init__(self, soundCapturer):
        super(FFTScope, self).__init__()

        self.soundCapturer = soundCapturer
        self.dtConfig = self.soundCapturer.dtConfig

        self.setWindowTitle("Frequency Domain")
        self.setWindowIcon(QtGui.QIcon('freq.png'))

        # Set up pyqtgraph FFT plot
        self.plotWidget = pg.PlotWidget(title="Real-time FFT Scope")
        self.setCentralWidget(self.plotWidget)

        self.fftCurve = self.plotWidget.plot(pen='b')
        self.maxPeakCurve = self.plotWidget.plot(pen='orange', style='--')  # Orange dashed line for max peaks
        self.plotWidget.showGrid(x=True, y=True)  # Enable grid

        self.plotWidget.addLegend() # Add legend
        self.fftCurve = self.plotWidget.plot(pen='cyan', name="Current FFT Data")
        self.maxPeakCurve = self.plotWidget.plot(pen='yellow', name="Max Peak FFT Data")  # Orange dashed line for max peaks

        self.plotWidget.setLogMode(x=True, y=False)  # Log scale on X-axis (frequency)
        self.plotWidget.setYRange(self.dtConfig["FrequencyDomainScopeSettings"]["yMinLimit"], self.dtConfig["FrequencyDomainScopeSettings"]["yMaxLimit"])
        self.plotWidget.setLabel('bottom', 'Frequency', units='Hz')
        self.plotWidget.setLabel('left', 'Magnitude [Bits]')

        # Initialize a max peaks array with very low values to start with
        self.maxPeaks = np.zeros(self.soundCapturer.iInputFramesPerBlock // 2)

        # Add scatter plot for marking clicked points
        self.markerPlot = pg.ScatterPlotItem(size=10, pen='w')  # Red markers with white outline
        self.plotWidget.addItem(self.markerPlot)

        # Enable mouse tracking for tooltip
        self.plotWidget.setMouseTracking(True)
        self.plotWidget.scene().sigMouseMoved.connect(self.show_tooltip)
        self.plotWidget.scene().sigMouseClicked.connect(self.mark_point)
        # Initialize a variable to store the persistent tooltip label
        self.persistentAnnotation = None

        # Connect signal for real-time FFT plotting
        self.soundCapturer.sigFFTDataReady.connect(self.update_fft_plot)

    def show_tooltip(self, pos):
        # Map the mouse position to plot coordinates
        mouse_point = self.plotWidget.plotItem.vb.mapSceneToView(pos)
        x = mouse_point.x()
        y = mouse_point.y()

        # Check if the plot is in log scale for x or y
        blXIsLog = self.plotWidget.getAxis('bottom').logMode
        blYIsLog = self.plotWidget.getAxis('left').logMode

        xValue = 10 ** x if blXIsLog else x
        yValue = 10 ** y if blYIsLog else y

        # Retrieve x and y axis bounds
        x_min, x_max = self.plotWidget.plotItem.vb.viewRange()[0]
        y_min, y_max = self.plotWidget.plotItem.vb.viewRange()[1]

        # Ensure coordinates are within range
        if x_min <= x <= x_max and y_min <= y <= y_max:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Frequency: {xValue:.2f} Hz\nMagnitude: {yValue:.2f} Bits")
        else:
            # Hide tooltip if mouse is out of plot range
            QtWidgets.QToolTip.hideText()

    def mark_point(self, event):
        """Mark the clicked point and display a persistent tooltip."""
        # Check if the left mouse button was clicked
        if event.button() != QtCore.Qt.LeftButton:
            return  # Ignore if it was not a left click
        
        # Map the clicked position to plot coordinates
        pos = event.scenePos()
        mouse_point = self.plotWidget.plotItem.vb.mapSceneToView(pos)
        x, y = mouse_point.x(), mouse_point.y()

        # Retrieve plot bounds
        x_min, x_max = self.plotWidget.plotItem.vb.viewRange()[0]
        y_min, y_max = self.plotWidget.plotItem.vb.viewRange()[1]

        # Ensure click is within bounds
        if x_min <= x <= x_max and y_min <= y <= y_max:
            # Adjust for log scale if applicable
            x_value = 10 ** x if self.plotWidget.getAxis('bottom').logMode else x
            y_value = 10 ** y if self.plotWidget.getAxis('left').logMode else y

            # Set the marker on the clicked point
            self.markerPlot.setData([x], [y])

        # Remove any existing annotation
        if hasattr(self, 'persistentAnnotation') and self.persistentAnnotation is not None:
            self.plotWidget.plotItem.removeItem(self.persistentAnnotation)

        # Create the annotation text
        annotation_text = f"Frequency: {x_value:.2f} Hz\nMagnitude: {y_value:.2f} Bits"
        
        # Create a pyqtgraph TextItem for the annotation
        self.persistentAnnotation = pg.TextItem(text=annotation_text, color='w', anchor=(0, 1))  # White text, anchor top-left

        # Position the annotation close to the clicked point with an offset for visibility
        self.persistentAnnotation.setPos(x, y)
        self.plotWidget.plotItem.addItem(self.persistentAnnotation)

    @pyqtSlot(np.ndarray, np.ndarray)
    def update_fft_plot(self, frequencies, fft_data):
        # Update the max peak values by comparing current FFT data with previously held max
        self.maxPeaks = np.maximum(self.maxPeaks, fft_data)

        # Update FFT plot with live data
        self.fftCurve.setData(frequencies, fft_data)
        # Update max peak plot with held peak values
        self.maxPeakCurve.setData(frequencies, self.maxPeaks)

class Scope(QMainWindow):
    def __init__(self, soundCapturer):
        super(Scope, self).__init__()

        self.soundCapturer = soundCapturer
        self.dtConfig = self.soundCapturer.dtConfig

        self.setWindowTitle("Time Domain")
        self.setWindowIcon(QtGui.QIcon('time.png'))

        # Setup pyqtgraph plot
        self.plotWidget = pg.PlotWidget(title="Real-time Audio Waveform")
        self.setCentralWidget(self.plotWidget)
        self.plotWidget.setYRange(self.dtConfig["TimeDomainScopeSettings"]["yMinLimit"], self.dtConfig["TimeDomainScopeSettings"]["yMaxLimit"])  # Set Y range for int16 audio data
        self.leftChannelCurve = self.plotWidget.plot(pen='r')  # Left channel in red
        self.rightChannelCurve = self.plotWidget.plot(pen='g')  # Right channel in green
        self.plotWidget.showGrid(x=True, y=True)  # Enable grid

        # Add legend
        self.plotWidget.addLegend()

        # Left and right channel curves with labels for the legend
        self.leftChannelCurve = self.plotWidget.plot(pen='r', name="Left Channel")  # Left channel in red
        self.rightChannelCurve = self.plotWidget.plot(pen='g', name="Right Channel")  # Right channel in green

        # Set axis labels
        self.plotWidget.setLabel('bottom', 'Time', units='s')  # X-axis for time in seconds
        self.plotWidget.setLabel('left', 'Sound Level [Bits]')  # Y-axis for sound level in bits

        # Calculate time axis based on InputBlockTimeInSeconds and sampling rate
        block_duration = self.dtConfig["InputBlockTimeInSeconds"]
        self.timeAxis = np.linspace(0, block_duration, self.soundCapturer.iInputFramesPerBlock)

        # Connect signal for real-time plotting
        self.soundCapturer.sigBlockCaptured.connect(self.update_plot)

    @pyqtSlot(bool)
    def update_plot(self, _):
        # Update left and right channel data with time as x-axis
        self.leftChannelCurve.setData(self.timeAxis, self.soundCapturer.leftArrayData)
        self.rightChannelCurve.setData(self.timeAxis, self.soundCapturer.rightArrayData)

class FFTBarVisualizer(QMainWindow):
    def __init__(self, soundCapturer):
        super(FFTBarVisualizer, self).__init__()

        self.soundCapturer = soundCapturer
        self.dtConfig = self.soundCapturer.dtConfig

        self.setWindowTitle("FFT Music Visualizer")
        self.setWindowIcon(QtGui.QIcon('freq.png'))

        self.fDecayFactor = self.dtConfig["FFTSpectrumVisualizerSettings"]["decayCoeff"]

        # Set up pyqtgraph FFT plot
        self.plotWidget = pg.PlotWidget(title="Real-time FFT Bar Graph")
        self.setCentralWidget(self.plotWidget)

        # Bar graph for FFT visualization
        self.barGraph = pg.BarGraphItem(x=[], height=[], width=1.0, brush='LightSeaGreen')
        self.plotWidget.addItem(self.barGraph)

        # Scatter plot for max peaks
        self.maxPeakDots = pg.ScatterPlotItem(size=10, brush='olivedrab')
        self.plotWidget.addItem(self.maxPeakDots)

        self.plotWidget.showGrid(x=True, y=True)
        self.plotWidget.setLogMode(x=False, y=False)
        self.plotWidget.setYRange(
            self.dtConfig["FFTSpectrumVisualizerSettings"]["yMaxLimit"],
            self.dtConfig["FFTSpectrumVisualizerSettings"]["yMinLimit"],
        )
        self.plotWidget.setLabel('bottom', 'Frequency', units='Hz')
        self.plotWidget.setLabel('left', 'Magnitude [Bits]')

        # Initialize max peaks array
        self.maxPeaks = np.zeros(self.soundCapturer.iInputFramesPerBlock // 2)

        # Connect signal for real-time FFT plotting
        self.soundCapturer.sigFFTDataReady.connect(self.update_bar_graph)

    @pyqtSlot(np.ndarray, np.ndarray)
    def update_bar_graph(self, frequencies, fft_data):
        # Update max peaks for reference (optional)
        self.maxPeaks = np.maximum(self.maxPeaks, fft_data)

        # TODO: fix log mode not working problem
        # transformFunction = lambda x: np.log10(x) if self.plotWidget.getAxis('bottom').logMode else x
        # xData = transformFunction(frequencies)

        # Update the bar graph
        self.barGraph.setOpts(x=frequencies, height=fft_data, width=(frequencies[1] - frequencies[0]))
        self.maxPeakDots.setData(frequencies, self.maxPeaks)

        self.maxPeaks *= self.fDecayFactor
        # # Update max peaks for reference (optional)
        # self.maxPeaks = np.maximum(self.maxPeaks, fft_data)

        # # Reduce data to fit into fewer bars (if needed)
        # num_bars = 50  # Adjust number of bars
        # bar_frequencies = np.interp(
        #     np.linspace(0, len(frequencies), num_bars),
        #     np.arange(len(frequencies)),
        #     frequencies
        # )
        # bar_heights = np.interp(
        #     np.linspace(0, len(fft_data), num_bars),
        #     np.arange(len(fft_data)),
        #     fft_data
        # )

        # # Update the bar graph
        # self.barGraph.setOpts(x=bar_frequencies, height=bar_heights, width=(frequencies[1] - frequencies[0])*len(frequencies)/num_bars)

class myWindow(QMainWindow):
    def __init__(self, p_sConfigDictPath):
        super(myWindow, self).__init__()
        self.ui = mainMainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QtGui.QIcon('img.png'))

        self.ui.btnResetFFTMaxHold.clicked.connect(self.clear_max_hold)

        self.sConfigPath = p_sConfigDictPath
        self.dtConfig = LoadConfig(self.sConfigPath)

        self.SoundCapturer = SoundCapturer(self.dtConfig)

        if self.dtConfig["TimeDomainScopeEnabled"]:
            # Setup Scope for real-time plotting
            self.scope = Scope(self.SoundCapturer)
            if self.dtConfig["TimeDomainScopeSettings"]["persistOnTop"]:
                self.scope.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
            self.scope.show()
        else:
            print("-> Time domain scope disabled in [swi_config.json]")

        if self.dtConfig["FrequencyDomainScopeEnabled"]:
            # Setup FFTScope for real-time FFT plotting
            self.fftScope = FFTScope(self.SoundCapturer)
            if self.dtConfig["FrequencyDomainScopeSettings"]["persistOnTop"]:
                self.fftScope.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
            self.fftScope.show()

            self.ui.btnResetFFTMaxHold.setEnabled(True)
        else:
            print("-> Frequency domain scope disabled in [swi_config.json]")

        if self.dtConfig["FFTSpectrumVisualizerEnabled"]:
            self.fftBarVisualizer = FFTBarVisualizer(self.SoundCapturer)
            if self.dtConfig["FFTSpectrumVisualizerSettings"]["persistOnTop"]:
                self.fftBarVisualizer.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
            self.fftBarVisualizer.show()
        else:
            print("-> FFT music visualizer disabled in [swi_config.json]")


        if self.dtConfig["ControlWindowSettings"]["persistOnTop"]:
            self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)

        self.SoundCapturer.start()

        self.ui.btnPauseContinue.clicked.connect(self.HandleBtnPauseContinue)

    def clear_max_hold(self):
        # Reset the max peak hold in the FFTScope
        if self.fftScope:
            self.fftScope.maxPeaks = np.zeros_like(self.fftScope.maxPeaks)  # Reset the max peaks array
            self.fftScope.maxPeakCurve.setData([], [])  # Clear the max peak curve

    def HandleBtnPauseContinue(self):
        if(self.SoundCapturer.blRun):
            self.SoundCapturer.blRun = False
            self.ui.btnPauseContinue.setText("Continue")
        else:
            self.SoundCapturer.blRun = True
            self.ui.btnPauseContinue.setText("Pause")

    def closeEvent(self, event):
        for window in QApplication.topLevelWidgets():
            window.close()



def app(p_sConfigDictPath):
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    try:
        win = myWindow(p_sConfigDictPath)
        win.show()
        sys.exit(app.exec_())
    except Exception as err:
        print(f"Error occurred: {err}")

if __name__ == "__main__":
    sConfigDictPath = sys.argv[1]
    app(sConfigDictPath)
