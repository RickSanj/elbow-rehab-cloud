from pandas import DataFrame

def compute_session_report(df: DataFrame):
    duration = 'None' # todo duration
    max_flexion = df["flexion_deg"].max()
    max_extention = df["flexion_deg"].min()
    max_pronation = df["pronation_deg"].max()
    max_supination = df["pronation_deg"].min()

    pain_level = 'None' #todo add pain level

    return max_flexion, max_extention, max_pronation, max_supination, pain_level