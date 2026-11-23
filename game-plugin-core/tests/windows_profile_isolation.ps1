# Run only on an isolated Windows machine/ephemeral CI runner with local admin rights.
# Creates an ephemeral local user and removes it in finally; does not touch real credentials.
param([Parameter(Mandatory=$true)][string]$BinaryDir)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Profile isolation test requires local administrator on an isolated runner' }
$id = [guid]::NewGuid().ToString('N').Substring(0,10)
$user = "nori_$id"
$dir = Join-Path $env:ProgramData "nori-dpapi-test-$id"
$created = $false
try {
  New-Item -ItemType Directory -Path $dir | Out-Null
  Copy-Item (Join-Path $BinaryDir 'nori_windows_vault_test.exe') $dir
  Get-ChildItem -Path $BinaryDir -Filter '*.dll' | Copy-Item -Destination $dir
  $pw = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)) + '!a9Z'
  $secure = ConvertTo-SecureString $pw -AsPlainText -Force
  $pw = $null
  New-LocalUser -Name $user -Password $secure -AccountNeverExpires | Out-Null
  $created = $true
  & icacls $dir /grant "${env:COMPUTERNAME}\${user}:(OI)(CI)M" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Could not grant test directory access' }
  $exe = Join-Path $dir 'nori_windows_vault_test.exe'
  $owner = Join-Path $dir 'owner.dpapi'
  $other = Join-Path $dir 'other.dpapi'
  & $exe write $owner; if ($LASTEXITCODE -ne 0) { throw 'Owner write failed' }
  & $exe read $owner; if ($LASTEXITCODE -ne 0) { throw 'Owner read failed' }
  $credential = [pscredential]::new(".\$user", $secure)
  foreach ($item in @(@('probe',$other), @('reject',$owner))) {
    $proc = Start-Process -FilePath $exe -ArgumentList @($item[0],('"'+$item[1]+'"')) -Credential $credential -LoadUserProfile -WindowStyle Hidden -PassThru -Wait
    if ($proc.ExitCode -ne 0) { throw "Second profile $($item[0]) failed: $($proc.ExitCode)" }
  }
  & $exe read $owner; if ($LASTEXITCODE -ne 0) { throw 'Owner cannot read after isolation test' }
  Write-Output 'PASS: second Windows profile can use its own DPAPI and cannot decrypt readable owner ciphertext'
} finally {
  if ($created) { Remove-LocalUser -Name $user -ErrorAction Continue }
  if (Test-Path $dir) { Remove-Item -Path $dir -Recurse -Force -ErrorAction Continue }
}
