"""DPAPI protects queued metadata for the current Windows user."""
import base64
import ctypes
import os
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def crypt(data, decrypt=False):
    if os.name!='nt': return data
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte))); result=Blob()
    library=ctypes.WinDLL('crypt32',use_last_error=True)
    function=library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise ValueError('Windows DPAPI queue protection failed for this user profile')
    try: return ctypes.string_at(result.data,result.size)
    finally:
        ctypes.memset(result.data,0,result.size)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p]; kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(result.data)

def encode(value):
    return ('dpapi:' + base64.b64encode(crypt(value.encode())).decode()) if os.name=='nt' else value

def decode(value):
    if value.startswith('dpapi:'): return crypt(base64.b64decode(value[6:]),True).decode()
    if os.name=='nt': raise ValueError('Unprotected queue record rejected')
    return value
