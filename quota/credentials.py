"""Windows Credential Manager storage; config contains only a reference."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def api():
    if os.name != "nt":
        raise OSError("内置凭据保存需要 Windows；其他系统请使用环境变量")
    dll = ctypes.WinDLL("Advapi32", use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    return dll


def write(reference: str, secret: str) -> None:
    encoded = secret.encode("utf-8")
    if not encoded or len(encoded) > 2560:
        raise ValueError("密钥不能为空且不能超过 2560 字节")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = Credential(
        Type=1,
        TargetName=reference,
        CredentialBlobSize=len(encoded),
        CredentialBlob=blob,
        Persist=2,
        UserName="AI Quota",
    )
    try:
        if not api().CredWriteW(ctypes.byref(credential), 0):
            raise OSError("Windows 凭据管理器保存失败")
    finally:
        ctypes.memset(blob, 0, len(encoded))


def read(reference: str) -> str | None:
    dll = api()
    pointer = ctypes.POINTER(Credential)()
    if not dll.CredReadW(reference, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise OSError("Windows 凭据管理器读取失败")
    try:
        return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode("utf-8")
    finally:
        dll.CredFree(pointer)


def delete(reference: str) -> None:
    if not api().CredDeleteW(reference, 1, 0) and ctypes.get_last_error() != 1168:
        raise OSError("Windows 凭据管理器删除失败")
