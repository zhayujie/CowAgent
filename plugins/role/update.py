
roles_list_path = "role_file_map.json"
import json5
from roles.load_role import get_role_list

def update_files():
    try:
        now_roles_list = get_role_list()
    except FileNotFoundError:
        now_roles_list = []
    try:
        with open(roles_list_path, "r", encoding="utf-8") as f:
            old_roles_map = json5.load(f)
    except FileNotFoundError:
        old_roles_map = {}
    old_roles_list = [item for item in old_roles_map.values()]

    add_list = [item for item in now_roles_list if item not in old_roles_list]
    del_list = [item for item in old_roles_list if item not in now_roles_list]

    if add_list:
        for item in add_list:
            with open(f"roles/{item}.json", "r", encoding="utf-8") as f:
                ret = json5.load(f)
                old_roles_map[ret["title"]] = item
    for del_item in del_list:
        for key, value in list(old_roles_map.items()):
            if value == del_item:
                del old_roles_map[key]
                break
    with open(roles_list_path, "w", encoding="utf-8") as f:
        json5.dump(old_roles_map, f, indent=4, ensure_ascii=False)


update_files()