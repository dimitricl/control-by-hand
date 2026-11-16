"""Coupe-circuit global : Ctrl+Option+Cmd+Espace active/désactive le contrôle de la souris.

Utilise un CGEventTap en écoute seule (macOS demande « Surveillance de l'entrée » au
Terminal). Si le tap ne peut pas être créé, on prévient et on continue sans (la touche
Espace de l'aperçu et Ctrl+C restent disponibles).
"""
import threading

from Quartz import (
    CGEventTapCreate, CGEventTapEnable, CGEventGetFlags, CGEventGetIntegerValueField,
    CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRun,
    kCFRunLoopCommonModes, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly, kCGEventKeyDown, kCGKeyboardEventKeycode,
    kCGEventFlagMaskControl, kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand,
    kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput,
)

KEY_SPACE = 49
MODS = kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskCommand


def start(on_toggle):
    """Lance l'écoute dans un thread démon. Renvoie True si le raccourci est actif."""
    ready = threading.Event()
    result = {"ok": False}

    def callback(proxy, etype, event, refcon):
        if etype in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(tap, True)       # macOS coupe parfois le tap : on le réarme
        elif etype == kCGEventKeyDown:
            if (CGEventGetFlags(event) & MODS) == MODS and \
                    CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode) == KEY_SPACE:
                on_toggle()
        return event

    def run():
        nonlocal tap
        tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                               kCGEventTapOptionListenOnly, 1 << kCGEventKeyDown, callback, None)
        if tap is None:
            ready.set()
            return
        src = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        result["ok"] = True
        ready.set()
        CFRunLoopRun()

    tap = None
    threading.Thread(target=run, daemon=True).start()
    ready.wait(2.0)
    return result["ok"]
