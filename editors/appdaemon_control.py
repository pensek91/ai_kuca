#!/usr/bin/env python3
"""
AppDaemon Restart/Reload Utility

Ova skripta omogućuje restart ili reload AppDaemon servisa iz editora ili wizarda.
"""
import os
import sys
import subprocess

MENU_OPTIONS = [
    ("Reload AppDaemon (config reload)", "reload"),
    ("Restart AppDaemon (full restart)", "restart"),
    ("Izlaz", "exit")
]

def show_menu():
    print("\n=== AppDaemon Kontrola ===")
    for idx, (label, _) in enumerate(MENU_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = input("Odaberi opciju: ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(MENU_OPTIONS):
            return MENU_OPTIONS[idx][1]
    except Exception:
        pass
    return None

def reload_appdaemon():
    print("[INFO] Pokrećem reload AppDaemona...")
    os.system("supervisorctl reload appdaemon || systemctl reload appdaemon || docker restart appdaemon")
    print("[INFO] Reload završen.")

def restart_appdaemon():
    print("[INFO] Pokrećem restart AppDaemona...")
    os.system("supervisorctl restart appdaemon || systemctl restart appdaemon || docker restart appdaemon")
    print("[INFO] Restart završen.")

if __name__ == "__main__":
    while True:
        action = show_menu()
        if action == "reload":
            reload_appdaemon()
        elif action == "restart":
            restart_appdaemon()
        elif action == "exit":
            print("Izlaz.")
            sys.exit(0)
        else:
            print("Nepoznata opcija. Pokušaj ponovno.")
