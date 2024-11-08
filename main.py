#!/usr/bin/python3
import pyaudiowpatch as pyaudio
from utilityFunctions import LoadConfig
from constants import *
from guiFiles.mainGui import Ui_MainWindow as mainMainWindow
import sys
import os
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot

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

                    if self.dtConfig["TimeDomainScopeEnabled"]:
                        # Emit signal for time domain plot
                        self.sigBlockCaptured.emit(True)

                    if self.dtConfig["FrequencyDomainScopeEnabled"]:
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
        self.fftCurve = self.plotWidget.plot(pen='b', name="Current FFT Data")
        self.maxPeakCurve = self.plotWidget.plot(pen='orange', name="Max Peak FFT Data", style='--')  # Orange dashed line for max peaks

        self.plotWidget.setLogMode(x=True, y=False)  # Log scale on X-axis (frequency)
        self.plotWidget.setYRange(self.dtConfig["FrequencyDomainScopeSettings"]["yMinLimit"], self.dtConfig["FrequencyDomainScopeSettings"]["yMaxLimit"])
        self.plotWidget.setLabel('bottom', 'Frequency', units='Hz')
        self.plotWidget.setLabel('left', 'Magnitude')

        # Initialize a max peaks array with very low values to start with
        self.maxPeaks = np.zeros(self.soundCapturer.iInputFramesPerBlock // 2)

        # Connect signal for real-time FFT plotting
        self.soundCapturer.sigFFTDataReady.connect(self.update_fft_plot)

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


class myWindow(QMainWindow):
    def __init__(self, p_sConfigDictPath):
        super(myWindow, self).__init__()
        self.ui = mainMainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QtGui.QIcon('img.png'))

        self.ui.btnResetFFTMaxHold.clicked.connect(self.clear_max_hold)

        self.runPauseState = "run"

        self.sConfigPath = p_sConfigDictPath
        self.dtConfig = LoadConfig(self.sConfigPath)

        self.SoundCapturer = SoundCapturer(self.dtConfig)

        if self.dtConfig["TimeDomainScopeEnabled"]:
            # Setup Scope for real-time plotting
            self.scope = Scope(self.SoundCapturer)
            self.scope.show()
        else:
            print("-> Time domain scope disabled in [swi_config.json]")

        if self.dtConfig["FrequencyDomainScopeEnabled"]:
            # Setup FFTScope for real-time FFT plotting
            self.fftScope = FFTScope(self.SoundCapturer)
            self.fftScope.show()

            self.ui.btnResetFFTMaxHold.setEnabled(True)
  
        else:
            print("-> Frequency domain scope disabled in [swi_config.json]")

        self.SoundCapturer.start()

    def clear_max_hold(self):
        # Reset the max peak hold in the FFTScope
        if self.fftScope:
            self.fftScope.maxPeaks = np.zeros_like(self.fftScope.maxPeaks)  # Reset the max peaks array
            self.fftScope.maxPeakCurve.setData([], [])  # Clear the max peak curve
    # TODO
    # def HandleBtnPauseContinue(self):
    #     if(self.runPauseState == "run"):
    #         self.ui.btnPauseContinue.setText("Pause")
    #     elif(self.runPauseState == "paused"):
    #         self.ui.btnPauseContinue.setText("Continue")
    #     else:
    #         self.ui.btnPauseContinue.setText("State Error")



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
