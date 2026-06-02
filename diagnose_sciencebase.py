import requests
import json

def diagnose_sciencebase(item_id):
    print(f"--- Diagnosing ScienceBase ID: {item_id} ---")
    url = f"https://www.sciencebase.gov/catalog/item/{item_id}?format=json"
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"Failed to connect to ScienceBase: {e}")
        return

    # 1. Check Parent Files
    parent_files = payload.get('files', [])
    if parent_files:
        print("\n[Files attached directly to Parent]")
        for f in parent_files:
            print(f"  -> {f.get('name')}  |  Size: {f.get('size')} bytes")
    else:
        print("\n[No files attached directly to Parent]")

    # 2. Check Child Files
    if payload.get('hasChildren'):
        print(f"\n[Parent has children. Scanning 1 level down...]")
        child_url = f"https://www.sciencebase.gov/catalog/items?parentId={item_id}&format=json&fields=title,files"
        
        children = requests.get(child_url).json().get('items', [])
        for child in children:
            print(f"\n  Child Name: {child.get('title')}")
            c_files = child.get('files', [])
            if c_files:
                for f in c_files:
                    print(f"    -> {f.get('name')}  |  Size: {f.get('size')} bytes")
            else:
                print("    -> [No files found in this child]")

if __name__ == "__main__":
    diagnose_sciencebase("686317a5d4be025653d31f09")