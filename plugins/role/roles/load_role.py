import os 

current_dir = os.path.dirname(__file__)

def get_role_list():
    role_list = []
    for file in os.listdir(current_dir):
        if file.endswith(".json"):
            role_list.append(file[:-5])
    return role_list