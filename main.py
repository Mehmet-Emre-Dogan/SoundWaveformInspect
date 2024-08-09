#!/usr/bin/python3
import pyaudiowpatch as pyaudio
from utilityFunctions import LoadConfig
import sys
import os
import numpy as np
import matplotlib.pyplot as plt

if os.name == 'nt': # Only if we are running on Windows
    from ctypes import windll
    k = windll.kernel32
    k.SetConsoleMode(k.GetStdHandle(-11), 7)

def main(p_sConfigDictPath):
    dtConfig = LoadConfig(p_sConfigDictPath)
    # if dtConfig == {}

    if(dtConfig["TimeDomainScopeEnabled"]):

        plt.ion() # Stop matplotlib windows from blocking

        # Setup figure, axis and initiate plot
        with plt.rc_context({'axes.edgecolor':'white', 'xtick.color':'dbffff', 'ytick.color':'dbffff', 'figure.facecolor':'#252526', 'axes.labelcolor':'white', 'figure.figsize':[16, 7]}):
            # Temporary rc parameters in effect
            scopeFig, (scopeAx1, scopeAx2) = plt.subplots(1, 2)
        
        # xdata, ydata = [], []
        scopeAx1Ln, = scopeAx1.plot([], [], '-', color="#00dbdb")
        scopeAx1.set_ylim(bottom=dtConfig["TimeDomainScopeSettings"]["yMinLimit"], top=dtConfig["TimeDomainScopeSettings"]["yMaxLimit"])
        scopeAx1.grid(linestyle="--")
        
        scopeAx1.set_facecolor("#252526")

        scopeAx1.set_xlabel("Time [ms]")
        scopeAx1.set_ylabel("Level [Bits]")
        scopeAx1.set_title("Left", color="white")

        scopeAx2Ln, = scopeAx2.plot([], [], '-', color="#00dbdb")
        scopeAx2.set_ylim(bottom=dtConfig["TimeDomainScopeSettings"]["yMinLimit"], top=dtConfig["TimeDomainScopeSettings"]["yMaxLimit"])
        scopeAx2.grid(linestyle="--")
        
        scopeAx2.set_facecolor("#252526")

        scopeAx2.set_xlabel("Time [ms]")
        # scopeAx2.set_ylabel("Level [Bits]")
        scopeAx2.set_title("Right", color="white")

    with pyaudio.PyAudio() as p:
        try:
            # Get default WASAPI info
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            print("Looks like WASAPI is not available on the system. Exiting...")
            exit()
    
        if dtConfig["UseSpeakerOrMic"] == "Speaker":
            # Get default WASAPI speakers
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    """
                    Try to find loopback device with same name(and [Loopback suffix]).
                    Unfortunately, this is the most adequate way at the moment.
                    """
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break
                else:
                    print("Default loopback output device not found.\n\nRun `python -m pyaudiowpatch` to check available devices.\nExiting...\n")
                    exit()

            NumberofChannels        = default_speakers["maxInputChannels"]
            iRate                   = int(default_speakers["defaultSampleRate"])
            iInputFramesPerBlock    = int(iRate * dtConfig["InputBlockTimeInSeconds"])
            iInputDeviceIndex       = default_speakers["index"]

        elif dtConfig["UseSpeakerOrMic"] == "Mic":
            # Get default WASAPI microphones
            default_microphones = p.get_device_info_by_index(wasapi_info["defaultInputDevice"])

            NumberofChannels        = default_microphones["maxInputChannels"]
            iRate                   = int(default_microphones["defaultSampleRate"])
            iInputFramesPerBlock    = int(iRate * dtConfig["InputBlockTimeInSeconds"])
            iInputDeviceIndex       = default_microphones["index"]
        else:
            raise Exception("Invalid <UseSpeakerOrMic> param. Use 'Speaker' or 'Mic'")

        with p.open(format=pyaudio.paInt16,
                    channels=NumberofChannels,
                    rate=iRate,
                    input=True,
                    frames_per_buffer=iInputFramesPerBlock,
                    input_device_index=iInputDeviceIndex
                    ) as stream:

            if(dtConfig["TimeDomainScopeEnabled"]):
                totalNumberOfSamples = stream._frames_per_buffer

                tickSizeInSec = dtConfig["InputBlockTimeInSeconds"] / totalNumberOfSamples
                timeArrayInMilliSec = np.arange(0, totalNumberOfSamples, 1) * tickSizeInSec * 1000

                scopeAx1Ln.set_xdata(timeArrayInMilliSec)
                scopeAx1.set_xlim(timeArrayInMilliSec[0] - tickSizeInSec*1000, timeArrayInMilliSec[-1] + tickSizeInSec*1000)

                scopeAx2Ln.set_xdata(timeArrayInMilliSec)
                scopeAx2.set_xlim(timeArrayInMilliSec[0] - tickSizeInSec*1000, timeArrayInMilliSec[-1] + tickSizeInSec*1000)


            while True:
                data = stream.read(iInputFramesPerBlock, exception_on_overflow=False)
                if(dtConfig["TimeDomainScopeEnabled"]):

                    # sampleRate = float(iRate)
                    # print(len(arrayData))
                    arrayData = np.frombuffer(data, dtype=np.int16) #np.int16

                    leftArrayData = arrayData[0::2]
                    rightArrayData = arrayData[1::2]

                    scopeAx1Ln.set_ydata(leftArrayData)
                    scopeAx2Ln.set_ydata(rightArrayData)

                    scopeFig.canvas.draw()
                    scopeFig.canvas.flush_events()

                    # # arrayData = arrayData[0:len(arrayData)//2]
                    # fftData   = np.fft.fft(arrayData)
                    # lenFftData = len(fftData)
                    # samplingPeriod = lenFftData / sampleRate
                    # freqArray  = np.arange(lenFftData) / samplingPeriod

                    # Reset the data in the plot
                    # ln.set_xdata(freqArray)
                    # ln.set_ydata(abs(fftData))

                    
                    # print(dtConfig["InputBlockTimeInSeconds"] / totalNumberOfSamples)
                    # print(len(timeArrayInMilliSec))
                    # print(len(leftArrayData))



                    # Rescale the axis so that the data can be seen in the plot
                    # if you know the bounds of your data you could just set this once
                    # so that the axis don't keep changing
                    # scopeAx1.relim()
                    # ax.autoscale_view()

                    # Update the window



if __name__ == "__main__":
    sConfigDictPath = sys.argv[1]
    main(sConfigDictPath)
