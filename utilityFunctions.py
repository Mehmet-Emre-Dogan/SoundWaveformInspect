from json import load
def LoadConfig(p_sConfigDictPath):
    dtConfigToReturn = {}
    with open(p_sConfigDictPath) as fptr:
        dtConfigToReturn = load(fptr)
    return dtConfigToReturn

def Saturate(p_Value, p_LowerLimit, p_UpperLimit):
    SaturatedValue = p_Value
    if SaturatedValue < p_LowerLimit:
        SaturatedValue = p_LowerLimit
    elif SaturatedValue > p_UpperLimit:
        SaturatedValue = p_UpperLimit
    
    return SaturatedValue