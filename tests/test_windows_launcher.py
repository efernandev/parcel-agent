import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "start-parcel.ps1"


def powershell(code):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def sourced(code):
    path = str(SCRIPT).replace("'", "''")
    return f"$ErrorActionPreference = 'Stop'; . '{path}'; " + code


def test_powershell_script_parses():
    path = str(SCRIPT).replace("'", "''")
    powershell(
        f"$tokens = $null; $errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { throw ($errors | Out-String) }"
    )


def test_missing_uv_shows_install_instructions():
    powershell(sourced("""
        function Get-Command { return $null }
        $failed = $false
        try { Find-Program 'uv.exe' (Join-Path $env:TEMP 'missing-uv.exe') } catch {
            if ($_.Exception.Message -notmatch 'astral-sh.uv') { throw }
            $failed = $true
        }
        if (-not $failed) { throw 'Missing uv must explain installation' }
    """))


def test_private_connection_uses_exact_dns_and_logged_in_user():
    powershell(sourced("""
        $status = '{"BackendState":"Running","Self":{"DNSName":"PC.personal.ts.net.","UserID":42},"User":{"42":{"LoginName":"Owner@example.com"}}}' | ConvertFrom-Json
        $connection = Get-PrivateConnection $status
        if ($connection.Url -cne 'https://pc.personal.ts.net:8443') { throw 'Wrong URL' }
        if ($connection.User -cne 'owner@example.com') { throw 'Wrong identity' }
        $status.BackendState = 'NeedsLogin'
        $rejected = $false
        try { Get-PrivateConnection $status } catch { $rejected = $true }
        if (-not $rejected) { throw 'Must reject disconnected Tailscale' }
    """))


def test_serve_configuration_never_overwrites_other_service_or_funnel():
    powershell(sourced("""
        if (Test-ParcelServe ('{}' | ConvertFrom-Json)) { throw 'Empty config' }
        $config = '{"TCP":{"8443":{"HTTPS":true}},"Web":{"pc.personal.ts.net:8443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8765"}}}}}' | ConvertFrom-Json
        if (-not (Test-ParcelServe $config)) { throw 'Own config not recognized' }
        $config.Web.'pc.personal.ts.net:8443'.Handlers.'/'.Proxy = 'http://127.0.0.1:9999'
        $rejected = $false
        try { Test-ParcelServe $config } catch { $rejected = $true }
        if (-not $rejected) { throw 'Must not overwrite other service' }
        $config.Web.'pc.personal.ts.net:8443'.Handlers.'/'.Proxy = 'http://127.0.0.1:8765'
        $config | Add-Member -NotePropertyName AllowFunnel -NotePropertyValue ('{"pc.personal.ts.net:8443":true}' | ConvertFrom-Json)
        $rejected = $false
        try { Test-ParcelServe $config } catch { $rejected = $true }
        if (-not $rejected) { throw 'Must reject public Funnel' }
    """))


def test_existing_server_is_checked_before_reuse():
    powershell(sourced("""
        Assert-ParcelHealth ([pscustomobject]@{app='parcel-agent';tailscale_url=''}) ''
        foreach ($health in @($null, [pscustomobject]@{app='other'}, [pscustomobject]@{app='parcel-agent';tailscale_url='https://pc.personal.ts.net:8443'})) {
            $rejected = $false
            try { Assert-ParcelHealth $health '' } catch { $rejected = $true }
            if (-not $rejected) { throw 'Unsafe server reuse' }
        }
    """))


@pytest.mark.parametrize("no_browser", [False, True])
def test_reused_server_explains_console_and_waits_only_for_interactive_launch(no_browser):
    value = "$true" if no_browser else "$false"
    powershell(sourced(f"""
        $Mode = 'Local'
        $NoBrowser = {value}
        $script:prompted = $false
        $script:opened = $false
        function Test-LocalPort {{ return $true }}
        function Read-ParcelHealth {{ return [pscustomobject]@{{app='parcel-agent';tailscale_url=''}} }}
        function Start-Process {{ param([string]$FilePath) $script:opened = $true }}
        function Read-Host {{ param([string]$Prompt) $script:prompted = $true; return '' }}
        $output = Start-Parcel 6>&1 | Out-String
        if ($output -notmatch 'Cerrar este aviso no detiene') {{ throw 'Missing explanation' }}
        if ($script:prompted -ne (-not $NoBrowser)) {{ throw 'Incorrect interactive pause' }}
        if ($script:opened -ne (-not $NoBrowser)) {{ throw 'Incorrect browser launch' }}
    """))


def test_shutdown_accepts_only_this_project_uvicorn_command():
    powershell(sourced("""
        $python = Join-Path $ProjectRoot '.venv\\Scripts\\python.exe'
        Assert-ParcelCommand ('"' + $python + '" -m uvicorn parcel_agent.app:app --host 127.0.0.1 --port 8765')
        foreach ($command in @(
            '"C:\\other\\python.exe" -m uvicorn parcel_agent.app:app',
            ('"' + $python + '" -m http.server 8765'),
            ('"' + $python + '" -m uvicorn other.app:app'),
            ''
        )) {
            $rejected = $false
            try { Assert-ParcelCommand $command } catch { $rejected = $true }
            if (-not $rejected) { throw 'Unsafe process accepted' }
        }
    """))


def test_shutdown_is_idempotent_without_tailscale():
    powershell(sourced("""
        function Get-ParcelStopTarget { return $null }
        function Get-Command { return $null }
        function Test-Path { return $false }
        $output = Stop-Parcel 6>&1 | Out-String
        if ($output -notmatch 'ya estaba detenido') { throw 'Missing idempotent result' }
    """))


def test_shutdown_request_matches_process_and_cannot_mask_newer_crash(tmp_path):
    marker = str(tmp_path / "stop-request.json").replace("'", "''")
    powershell(sourced(f"""
        $ShutdownFile = '{marker}'
        $started = [datetime]::UtcNow.AddMinutes(-1)
        @{{process_id=123;parent_id=456;requested_at=[datetime]::UtcNow.ToString('o')}} | ConvertTo-Json | Set-Content $ShutdownFile
        if (Test-RequestedStop 789 $started) {{ throw 'Wrong process accepted' }}
        if (Test-RequestedStop 456 ([datetime]::UtcNow.AddMinutes(1))) {{ throw 'Stale request accepted' }}
        if (-not (Test-RequestedStop 456 $started)) {{ throw 'Parent launcher not recognized' }}
        if (Test-Path $ShutdownFile) {{ throw 'Request not consumed' }}
    """))


def test_shutdown_refuses_foreign_listener_before_touching_tailscale():
    powershell(sourced("""
        function Test-LocalPort { return $true }
        function Read-ParcelHealth { return [pscustomobject]@{app='other'} }
        function Read-TailscaleJson { throw 'Must not reach Tailscale' }
        $rejected = $false
        try { Stop-Parcel } catch {
            if ($_.Exception.Message -notmatch 'ningun proceso ajeno') { throw }
            $rejected = $true
        }
        if (-not $rejected) { throw 'Foreign server not rejected' }
    """))


@pytest.mark.parametrize("mobile_error", [False, True])
def test_shutdown_stops_backend_even_if_mobile_cleanup_fails(tmp_path, mobile_error):
    marker = str(tmp_path / "stop-request.json").replace("'", "''")
    failure = "$true" if mobile_error else "$false"
    powershell(sourced(f"""
        $ShutdownFile = '{marker}'
        $script:mobileError = {failure}
        $script:killed = $false
        $script:process = [pscustomobject]@{{Id=123;HasExited=$false}}
        $script:process | Add-Member -MemberType ScriptMethod -Name Kill -Value {{ $script:killed = $true; $this.HasExited = $true }}
        $script:process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($timeout) return $true }}
        function Get-ParcelStopTarget {{ return @{{Process=$script:process;ParentId=456}} }}
        function Get-Command {{ return [pscustomobject]@{{Source=(Join-Path $PSHOME 'powershell.exe')}} }}
        function Read-TailscaleJson {{
            if ($script:mobileError) {{ throw 'Simulated Tailscale failure' }}
            return [pscustomobject]@{{}}
        }}
        function Test-LocalPort {{ return $false }}
        $failed = $false
        try {{ Stop-Parcel }} catch {{
            if ($_.Exception.Message -notmatch 'acceso movil') {{ throw }}
            $failed = $true
        }}
        if (-not $script:killed) {{ throw 'Backend was not stopped' }}
        if ($failed -ne $script:mobileError) {{ throw 'Incorrect cleanup result' }}
        $request = Get-Content $ShutdownFile -Raw | ConvertFrom-Json
        if ($request.process_id -ne 123) {{ throw 'Missing shutdown request' }}
    """))