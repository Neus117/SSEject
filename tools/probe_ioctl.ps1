# Disk attribute IOCTL probe (run in an elevated PowerShell).
# Reports GET/SET results and Win32 error codes for \\.\PhysicalDriveN so we can
# see exactly which buffer size / version the driver accepts.
param([int]$Disk = 2)

$ErrorActionPreference = 'Stop'

Write-Host "=== disk $Disk（请先插好盘；脚本只做无副作用写回） ==="
if (-not (Get-Disk -Number $Disk -ErrorAction SilentlyContinue)) {
    Write-Host "disk $Disk not present - plug it in first"
    exit 2
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class Probe {
    public const uint GENERIC_READ = 0x80000000;
    public const uint GENERIC_WRITE = 0x40000000;
    public const uint FILE_SHARE_READ = 1;
    public const uint FILE_SHARE_WRITE = 2;
    public const uint OPEN_EXISTING = 3;

    public const uint IOCTL_DISK_GET_DISK_ATTRIBUTES = 0x000700F0;
    public const uint IOCTL_DISK_SET_DISK_ATTRIBUTES = 0x0007C0F4;

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateFileW(string name, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr template);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool DeviceIoControl(IntPtr handle, uint code,
        IntPtr inBuffer, uint inSize, IntPtr outBuffer, uint outSize,
        out uint returned, IntPtr overlapped);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr handle);
}
'@

$handle = [Probe]::CreateFileW("\\.\PhysicalDrive$Disk",
    ([Probe]::GENERIC_READ -bor [Probe]::GENERIC_WRITE),
    ([Probe]::FILE_SHARE_READ -bor [Probe]::FILE_SHARE_WRITE),
    [IntPtr]::Zero, [Probe]::OPEN_EXISTING, 0, [IntPtr]::Zero)
if ($handle -eq [IntPtr]::Zero -or $handle -eq [IntPtr]::new(-1)) {
    Write-Host ("open failed, GetLastError = {0}" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error())
    exit 1
}
Write-Host "handle opened OK"

function Invoke-Get([int]$outSize) {
    $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($outSize)
    [Runtime.InteropServices.Marshal]::WriteInt32($buffer, 0, $outSize)  # Version
    $returned = 0
    $ok = [Probe]::DeviceIoControl($handle, [Probe]::IOCTL_DISK_GET_DISK_ATTRIBUTES,
        [IntPtr]::Zero, 0, $buffer, $outSize, [ref]$returned, [IntPtr]::Zero)
    $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    $version = [Runtime.InteropServices.Marshal]::ReadInt32($buffer, 0)
    $attributes = [Runtime.InteropServices.Marshal]::ReadInt64($buffer, 8)
    [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
    Write-Host ("GET outSize={0,-4} ok={1,-5} error={2,-4} returned={3} version={4} attributes=0x{5:X}" -f `
        $outSize, $ok, $err, $returned, $version, $attributes)
    return @{ ok = $ok; attributes = $attributes }
}

$get16 = Invoke-Get 16
$null = Invoke-Get 32

function Invoke-Set([int]$size, [int]$version, [int]$persist, [int]$attributes) {
    $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    for ($i = 0; $i -lt $size; $i++) { [Runtime.InteropServices.Marshal]::WriteByte($buffer, $i, 0) }
    [Runtime.InteropServices.Marshal]::WriteInt32($buffer, 0, $version)   # Version
    if ($size -ge 32) {
        [Runtime.InteropServices.Marshal]::WriteByte($buffer, 4, $persist) # Persist
        [Runtime.InteropServices.Marshal]::WriteInt32($buffer, 8, $attributes)
        [Runtime.InteropServices.Marshal]::WriteInt32($buffer, 12, 1)     # mask = OFFLINE
    }
    $returned = 0
    $ok = [Probe]::DeviceIoControl($handle, [Probe]::IOCTL_DISK_SET_DISK_ATTRIBUTES,
        $buffer, $size, [IntPtr]::Zero, 0, [ref]$returned, [IntPtr]::Zero)
    $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
    Write-Host ("SET size={0,-4} version={1,-4} persist={2} ok={3,-5} error={4}" -f $size, $version, $persist, $ok, $err)
}

$current = 0
if ($get16.ok) { $current = [int]($get16.attributes -band 1) }
Write-Host ("current offline bit = {0}（只做无副作用的写回，不改变磁盘状态）" -f $current)
foreach ($persist in 0, 1) {
    foreach ($combo in @(@(32,32), @(32,16), @(16,16))) {
        Invoke-Set $combo[0] $combo[1] $persist $current
    }
}

[Probe]::CloseHandle($handle) | Out-Null
Write-Host "done"
