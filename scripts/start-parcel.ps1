param(
    [ValidateSet('Local', 'Private', 'DisablePrivate', 'Stop')]
    [string]$Mode = 'Local',
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LocalUrl = 'http://127.0.0.1:8765'
$PrivatePort = 8443
$ShutdownFile = Join-Path $ProjectRoot 'data\stop-request.json'

function Get-Property($Object, [string]$Name) {
    if ($null -ne $Object) {
        $property = $Object.PSObject.Properties[$Name]
        if ($null -ne $property) { return $property.Value }
    }
    return $null
}

function Find-Program([string]$Name, [string]$Fallback) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if (Test-Path -LiteralPath $Fallback -PathType Leaf) { return $Fallback }
    if ($Name -eq 'uv.exe') {
        throw 'No se encuentra uv. Instalala con winget install --id=astral-sh.uv -e o desde https://docs.astral.sh/uv/getting-started/installation/ y vuelve a abrir este acceso.'
    }
    throw "No se encuentra $Name. Instala el programa y vuelve a abrir este acceso."
}

function Read-TailscaleJson([string]$Executable, [string[]]$Arguments) {
    $output = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Tailscale no responde. Abre su aplicacion y comprueba la conexion.'
    }
    return ConvertFrom-Json -InputObject ($output -join "`n")
}

function Get-PrivateConnection($Status) {
    if ((Get-Property $Status 'BackendState') -ne 'Running') {
        throw 'Abre Tailscale en el PC, inicia sesion y conecta este equipo antes de continuar.'
    }
    $self = Get-Property $Status 'Self'
    $hostname = [string](Get-Property $self 'DNSName')
    $hostname = $hostname.TrimEnd('.').ToLowerInvariant()
    if ($hostname -notmatch '^[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net$') {
        throw 'Tailscale no proporciona un nombre privado valido. Comprueba MagicDNS en tu red.'
    }
    $profile = Get-Property (Get-Property $Status 'User') ([string](Get-Property $self 'UserID'))
    $login = [string](Get-Property $profile 'LoginName')
    if ([string]::IsNullOrWhiteSpace($login)) {
        throw 'No se identifica un usuario personal de Tailscale. No uses un equipo etiquetado para este acceso.'
    }
    return @{ Url = "https://${hostname}:$PrivatePort"; User = $login.Trim().ToLowerInvariant() }
}

function Test-ParcelServe($Config) {
    $tcp = Get-Property (Get-Property $Config 'TCP') ([string]$PrivatePort)
    if ($null -eq $tcp) { return $false }
    $web = Get-Property $Config 'Web'
    $routes = @()
    if ($null -ne $web) {
        $routes = @($web.PSObject.Properties | Where-Object { $_.Name.EndsWith(":$PrivatePort") })
    }
    $handlers = if ($routes.Count -eq 1) { Get-Property $routes[0].Value 'Handlers' } else { $null }
    $handler = Get-Property $handlers '/'
    if (
        (Get-Property $tcp 'HTTPS') -ne $true -or $routes.Count -ne 1 -or
        $null -eq $handlers -or @($handlers.PSObject.Properties).Count -ne 1 -or
        (Get-Property $handler 'Proxy') -ne $LocalUrl
    ) {
        throw "El puerto privado $PrivatePort ya tiene otro servicio. No se modificara."
    }
    $funnel = Get-Property $Config 'AllowFunnel'
    if ($null -ne $funnel) {
        foreach ($entry in $funnel.PSObject.Properties) {
            if ($entry.Name.EndsWith(":$PrivatePort") -and $entry.Value) {
                throw 'El puerto 8443 tiene Funnel publico activo. Desactivalo en Tailscale antes de usar Parcel.'
            }
        }
    }
    return $true
}

function Read-ParcelHealth {
    try { return Invoke-RestMethod -Uri "$LocalUrl/api/health" -TimeoutSec 2 }
    catch { return $null }
}

function Assert-ParcelHealth($Health, [string]$PrivateUrl) {
    if ((Get-Property $Health 'app') -ne 'parcel-agent') {
        throw 'El puerto 8765 esta ocupado por otra aplicacion o una version antigua de Parcel. Cierra su ventana y vuelve a intentarlo.'
    }
    if ((Get-Property $Health 'tailscale_url') -cne $PrivateUrl) {
        throw 'Parcel ya esta abierto en otro modo. Cierra su ventana antes de cambiar entre PC y movil.'
    }
}

function Test-LocalPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', 8765)
        return $true
    }
    catch [System.Net.Sockets.SocketException] { return $false }
    finally { $client.Dispose() }
}

function Assert-ParcelCommand([string]$CommandLine) {
    $command = [regex]::Match(
        $CommandLine,
        '^\s*(?:"(?<python>[^"]+)"|(?<python>\S+))\s+-m\s+uvicorn\s+parcel_agent\.app:app(?:\s|$)'
    )
    $expected = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not $command.Success -or -not [string]::Equals(
        $command.Groups['python'].Value, $expected, [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw 'El proceso del puerto 8765 no se identifica como el servidor de este proyecto. No se cerrara. Usa su consola original.'
    }
}

function Get-ParcelStopTarget {
    if (-not (Test-LocalPort)) { return $null }
    if ((Get-Property (Read-ParcelHealth) 'app') -ne 'parcel-agent') {
        throw 'El puerto 8765 no responde como Parcel. No se cerrara ningun proceso ajeno.'
    }
    $listeners = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($listeners.Count -ne 1) { throw 'No se puede identificar con seguridad el proceso de Parcel. Usa su consola original.' }
    $process = Get-Process -Id $listeners[0] -ErrorAction Stop
    $null = $process.Handle
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    Assert-ParcelCommand ([string](Get-Property $info 'CommandLine'))
    if ($process.HasExited) { return $null }
    return @{ Process = $process; ParentId = [int](Get-Property $info 'ParentProcessId') }
}

function Test-RequestedStop([int]$ServerId, [datetime]$StartedAt) {
    if (-not (Test-Path -LiteralPath $ShutdownFile)) { return $false }
    try {
        $request = Get-Content -LiteralPath $ShutdownFile -Raw | ConvertFrom-Json
        $matchesProcess = $ServerId -in @($request.process_id, $request.parent_id)
        $requestedAt = [datetime]::Parse(
            $request.requested_at, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        if ($matchesProcess -and $requestedAt -ge $StartedAt.ToUniversalTime()) {
            Remove-Item -LiteralPath $ShutdownFile -Force
            return $true
        }
    }
    catch { return $false }
    return $false
}

function Stop-Parcel {
    $target = Get-ParcelStopTarget
    $issues = New-Object 'System.Collections.Generic.List[string]'
    $tailscale = Get-Command 'tailscale.exe' -CommandType Application -ErrorAction SilentlyContinue
    $tailscalePath = if ($tailscale) { $tailscale.Source } else { "$env:ProgramFiles\Tailscale\tailscale.exe" }
    if (Test-Path -LiteralPath $tailscalePath -PathType Leaf) {
        try {
            if (Test-ParcelServe (Read-TailscaleJson $tailscalePath @('serve', 'status', '--json'))) {
                & $tailscalePath serve --bg --https=8443 off
                if ($LASTEXITCODE -ne 0) { throw 'Tailscale no ha cerrado la ruta privada.' }
                Write-Host 'Acceso movil de Parcel desactivado.'
            }
        }
        catch { $issues.Add('No se pudo desactivar el acceso movil. Revisa Tailscale; no se han modificado servicios ajenos.') }
    }
    if ($null -ne $target) {
        $process = $target.Process
        if (-not $process.HasExited) {
            try {
                $null = New-Item -ItemType Directory -Path (Split-Path -Parent $ShutdownFile) -Force
                @{
                    process_id = $process.Id
                    parent_id = $target.ParentId
                    requested_at = [datetime]::UtcNow.ToString('o')
                } | ConvertTo-Json | Set-Content -LiteralPath $ShutdownFile -Encoding ASCII
            }
            catch { Write-Warning 'No se pudo registrar el cierre intencionado. La consola original puede mostrarlo como un error.' }
            $process.Kill()
            if (-not $process.WaitForExit(10000)) { throw 'Parcel no ha terminado de cerrarse. Revisa su consola original.' }
        }
        if (Test-LocalPort) { throw 'El puerto 8765 sigue ocupado. No se cerraran otros procesos automaticamente.' }
        Write-Host 'Servidor de Parcel detenido.' -ForegroundColor Green
    }
    else { Write-Host 'Parcel ya estaba detenido.' }
    Write-Host 'No se han borrado paquetes, claves ni autorizaciones. No se ha cerrado el navegador ni Tailscale.'
    if ($issues.Count) { throw ($issues -join ' ') }
}

function Start-Parcel {
    $server = $null
    $tailscale = $null
    $privateUrl = ''
    $ownsServe = $false
    Push-Location -LiteralPath $ProjectRoot
    try {
        if ($Mode -eq 'Stop') {
            Stop-Parcel
            if (-not $NoBrowser) { $null = Read-Host 'Pulsa Entrar para cerrar este aviso' }
            return
        }
        if ($Mode -ne 'Local') {
            try {
                $tailscale = Find-Program 'tailscale.exe' "$env:ProgramFiles\Tailscale\tailscale.exe"
            }
            catch {
                throw 'Instala Tailscale desde https://tailscale.com/download/windows, inicia sesion y vuelve a ejecutar este acceso. Instala tambien Tailscale en el movil con la misma cuenta.'
            }
            $serveConfig = Read-TailscaleJson $tailscale @('serve', 'status', '--json')
            $alreadyServing = Test-ParcelServe $serveConfig
            if ($Mode -eq 'DisablePrivate') {
                if ($alreadyServing) {
                    & $tailscale serve --bg --https=8443 off
                    if ($LASTEXITCODE -ne 0) { throw 'No se pudo desactivar Serve. Compruebalo en Tailscale.' }
                }
                Write-Host 'Acceso movil desactivado. No se han modificado otros servicios.'
                return
            }
            $connection = Get-PrivateConnection (Read-TailscaleJson $tailscale @('status', '--json'))
            $privateUrl = $connection.Url
            $env:TAILSCALE_URL = $privateUrl
            $env:TAILSCALE_USER = $connection.User
        }
        else {
            $env:TAILSCALE_URL = ''
            $env:TAILSCALE_USER = ''
        }

        $running = Test-LocalPort
        if ($running) {
            Assert-ParcelHealth (Read-ParcelHealth) $privateUrl
        }
        else {
            $uv = Find-Program 'uv.exe' "$HOME\.local\bin\uv.exe"
            Write-Host 'Preparando Parcel. La primera vez puede descargar Python y las dependencias...'
            & $uv sync --locked --no-dev
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Python. Revisa tu conexion y los mensajes anteriores.' }
            $python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
            $server = Start-Process -FilePath $python -WorkingDirectory $ProjectRoot -NoNewWindow -PassThru -ArgumentList @(
                '-m', 'uvicorn', 'parcel_agent.app:app', '--host', '127.0.0.1', '--port', '8765', '--no-proxy-headers'
            )
            $serverStartedAt = $server.StartTime.ToUniversalTime()
            $timer = [System.Diagnostics.Stopwatch]::StartNew()
            $health = $null
            while (-not $server.HasExited -and $timer.Elapsed.TotalSeconds -lt 30) {
                $health = Read-ParcelHealth
                if ($null -ne $health) { break }
                $null = $server.WaitForExit(200)
            }
            if ($server.HasExited) { throw 'El servidor se ha cerrado antes de arrancar. Revisa el error anterior.' }
            Assert-ParcelHealth $health $privateUrl
        }

        if ($Mode -eq 'Private') {
            Write-Host 'Activando HTTPS privado. Si Tailscale pide habilitar certificados, sigue su enlace.'
            $ownsServe = -not $running
            & $tailscale serve --bg --https=8443 $LocalUrl
            if ($LASTEXITCODE -ne 0) {
                throw 'No se pudo activar Serve. Habilita HTTPS en tu red Tailscale y vuelve a intentarlo.'
            }
            Write-Host "URL para el movil: $privateUrl" -ForegroundColor Green
            Write-Host 'Conecta Tailscale en el movil con la misma cuenta. Puedes guardar esta URL como favorito.'
        }
        Write-Host "URL en este PC: $LocalUrl" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process $LocalUrl }
        if ($null -ne $server) {
            Write-Host 'Deja esta ventana abierta. Pulsa Ctrl+C para detener Parcel.'
            $server.WaitForExit()
            $requestedStop = Test-RequestedStop $server.Id $serverStartedAt
            if ($server.ExitCode -ne 0 -and -not $requestedStop) { throw 'Parcel se ha detenido con un error. Revisa los mensajes anteriores.' }
            Write-Host 'Parcel se ha cerrado.'
        }
        else {
            Write-Host 'Parcel ya estaba abierto; se utiliza el servidor existente.'
            Write-Host 'Esta ventana es solo un aviso. Los registros siguen en la consola donde se inicio Parcel.'
            Write-Host 'Cerrar este aviso no detiene el servidor existente.'
            if (-not $NoBrowser) {
                $null = Read-Host 'Pulsa Entrar para cerrar este aviso'
            }
        }
    }
    finally {
        if ($ownsServe -and $null -ne $tailscale) {
            try {
                if (Test-ParcelServe (Read-TailscaleJson $tailscale @('serve', 'status', '--json'))) {
                    & $tailscale serve --bg --https=8443 off
                    if ($LASTEXITCODE -ne 0) { throw 'Tailscale no ha cerrado la ruta.' }
                }
            }
            catch { Write-Warning 'No se ha podido cerrar la ruta privada de Parcel. Revisa Tailscale o usa Desactivar acceso movil.bat.' }
        }
        if ($null -ne $server -and -not $server.HasExited) {
            Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        }
        Pop-Location
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Start-Parcel }
    catch {
        Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}