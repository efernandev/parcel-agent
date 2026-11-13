# AlPunto

Bandeja personal de paquetes **disponibles para recoger**. Muestra que paquete
es, donde esta, hasta cuando puedes recogerlo y los codigos o documentos originales
del correo. Pensada para vivir en Ginebra y recoger tambien en Francia.

AlPunto es el nombre visible de la aplicacion. Los accesos BAT y el paquete
`parcel_agent` conservan sus nombres originales para mantener la compatibilidad.

## Arrancar

Requisitos: Python 3.11 o superior y [uv](https://docs.astral.sh/uv/getting-started/installation/).
En PowerShell, desde la carpeta del proyecto:

```powershell
uv sync --group dev
uv run python -m uvicorn parcel_agent.app:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

Abre <http://127.0.0.1:8765>. **Ver ejemplo** carga una demo con tres recogidas y un
QR ficticio real, sin conectar cuentas ni modificar la base de datos. No hay que
configurar Gemini para probarla. Si el puerto esta ocupado, usa otro.

No publiques este servidor en Internet ni lo arranques con `--host 0.0.0.0`:
esta version es local y no tiene autenticacion de usuarios.

## Windows: Doble Clic

- **`Iniciar Parcel.bat`** prepara las dependencias, arranca el servidor y abre
  el navegador en <http://127.0.0.1:8765>. Funciona aunque la carpeta tenga espacios
  o se abra desde otra ubicacion. Necesitas instalar uv una vez; uv puede descargar
  Python si falta una version compatible.
- **`Iniciar Parcel movil.bat`** arranca la misma app y activa una URL HTTPS
  privada mediante Tailscale Serve. Muestra la URL exacta para guardar en el movil.
- **`Desactivar acceso movil.bat`** retira solo la ruta privada de Parcel del
  puerto 8443, sin resetear toda la configuracion de Tailscale.
- **`Cerrar Parcel.bat`** detiene el servidor de este proyecto y retira su ruta
	privada si Tailscale esta instalado. No borra datos, no desconecta Gmail ni cierra
	el navegador, VS Code o Tailscale. Puedes cerrar la pestana del navegador despues.

Para apagar Parcel sin buscar la consola, haz doble clic en **`Cerrar Parcel.bat`**.
El acceso comprueba la aplicacion y el comando del proceso antes de detenerlo;
no mata todos los procesos Python ni cualquier programa que ocupe el puerto.
Si ya estaba apagado, lo indica sin error. Si no puede identificarlo con seguridad,
no lo detiene y te pide usar la consola original. No necesita instalar uv ni
Tailscale para cerrar el servidor local.

Espera a que termine una sincronizacion antes de cerrar: el apagado termina el
proceso y puede interrumpir operaciones en curso. Los paquetes ya guardados se
conservan. Si falla la limpieza de Tailscale, aun asi intenta detener el servidor
y muestra que queda pendiente revisar la ruta privada. No cierra servicios ajenos.

Deja abierta la ventana del lanzador que arranca el servidor. **Ctrl+C** tambien lo detiene
y, en modo movil, intenta retirar su ruta privada. Si cierras la ventana a la fuerza
o se apaga el PC, la ruta de Serve puede permanecer configurada: utiliza el acceso
de desactivacion para quitarla. El servidor no se inicia automaticamente al encender
Windows; vuelve a abrir el acceso cuando quieras usarlo.

Si Parcel ya esta abierto en el mismo modo, el acceso reutiliza ese servidor.
La nueva ventana muestra un aviso y espera a que pulses Entrar; cerrarla no detiene
Parcel. Los registros siguen en la consola original, que puede estar en el panel
Terminal de VS Code si se arranco desde el editor. Solo la ventana que arranco
realmente el servidor debe permanecer abierta mientras lo usas.
Para cambiar de PC a movil o viceversa, cierra primero la ventana anterior. Si el
puerto 8765 pertenece a otro programa o a una version antigua de Parcel, el lanzador
se detiene con una explicacion, sin matar procesos ajenos.

Los accesos ejecutan `scripts/start-parcel.ps1` mediante PowerShell de Windows.
No son un ejecutable independiente ni requieren permisos de administrador para
arrancar Parcel. Si Windows bloquea un archivo descargado, revisa su procedencia y
sus propiedades; no desactives globalmente las protecciones del equipo.

## Primer Arranque En Otro PC Windows

1. Copia el proyecto completo a una carpeta del otro PC o clona el repositorio.
	No copies `.venv`: se crea de nuevo en cada equipo. Asegurate de que esten
	incluidos `uv.lock`, `pyproject.toml`, `scripts/` y `parcel_agent/`.
2. Instala `uv` una vez desde PowerShell:

	```powershell
	winget install --id=astral-sh.uv -e
	```

	Tambien puedes usar el instalador oficial de `uv`. No hace falta instalar
	Python manualmente: al abrir **`Iniciar Parcel.bat`**, `uv` instala una version
	compatible de Python y prepara las dependencias fijadas en `uv.lock`.
3. Crea `.env` a partir de la plantilla si aun no existe:

	```powershell
	Copy-Item .env.example .env
	```

	Configura `GEMINI_API_KEY` en `.env` con tu clave de Google AI Studio. No
	compartas `.env` ni subas la clave a Git. Sin una clave configurada puedes abrir la demo,
	pero no sincronizar correos reales.
4. Para conectar Gmail, coloca el JSON OAuth de tipo **Desktop app** en la raiz
	del proyecto como `credentials.json`. Puedes descargarlo de tu proyecto Google
	Cloud o transferirlo de forma privada; no lo subas a Git. Pulsa **Conectar
	Gmail** desde el navegador del PC y autoriza la cuenta. La autorizacion se
	guarda en el almacen de credenciales de Windows, asi que hay que autorizarla
	de nuevo en cada PC; no copies tokens del otro equipo.
5. Haz doble clic en **`Iniciar Parcel.bat`**. La primera vez necesita Internet
	para preparar Python y las dependencias. Se abrira `http://127.0.0.1:8765`;
	**Ver ejemplo** funciona sin Gmail ni IA. Para el acceso movil, configura
	Tailscale aparte siguiendo la seccion siguiente.

La base de datos `data/parcels.db` y `.env` no se incluyen en Git. Si necesitas
conservar el historial, detén Parcel y transfiere la base de datos de forma
privada. No es necesario copiarla para una instalacion nueva.

## Movil U Otro PC: Acceso Privado

Configuracion inicial, una sola vez:

1. Instala [Tailscale para Windows](https://tailscale.com/download/windows) en
	este PC e inicia sesion. La instalacion puede pedir permisos de administrador:
	realizala tu desde Windows.
2. Instala Tailscale en Android/iPhone, u otro PC, e inicia sesion con **la misma
	cuenta personal**. Mantenlo conectado en los dispositivos que quieras usar.
3. En el PC, ejecuta **`Iniciar Parcel movil.bat`**. Si Tailscale pide habilitar
	HTTPS/certificados, sigue el enlace de autorizacion que muestra y vuelve a
	intentarlo cuando termine. La red debe tener MagicDNS y HTTPS habilitados.
4. Copia al navegador del movil la URL que aparece, de la forma
	`https://tu-equipo.tu-red.ts.net:8443`. Es una direccion de ejemplo: utiliza la
	que muestra tu lanzador. Puedes guardarla como favorito.

No tienes que estar en el mismo wifi: tambien sirve con datos moviles mientras
Tailscale este conectado. **El PC debe estar encendido, sin suspension, con Parcel
ejecutandose y conexion a Internet.** No es un alojamiento en la nube.

La URL no es publica: usamos **Serve**, nunca **Funnel**, y no abrimos puertos del
router. La app solo escucha en `127.0.0.1`. El lanzador obtiene de Tailscale el
nombre exacto del equipo y el usuario propietario, y los pasa unicamente al proceso
del servidor; no hay que guardarlos a mano en `.env`. El backend comprueba la
identidad que anade Serve y rechaza otros usuarios, dispositivos etiquetados sin
identidad y solicitudes sin autenticar, incluso aunque conozcan la URL. Tambien
se aplican las reglas de acceso de tu red Tailscale. No compartas tu cuenta.

Esta proteccion depende de mantener el backend en localhost, detras de Serve;
no sustituyas esto por abrir el puerto a la red. No uses Funnel. Si el puerto
privado 8443 ya aloja otro servicio, el lanzador no lo modifica. La desactivacion
tampoco ejecuta `tailscale serve reset` ni cambia servicios de otros puertos.

La primera autorizacion de **Gmail se hace desde el navegador del PC**, en la URL
local. El flujo de Google abre una ventana y recibe su respuesta en ese equipo;
el movil podra sincronizar y consultar los paquetes cuando Gmail este conectado.
La clave de IA y los datos permanecen configurados en el PC; no tienes que
configurarlos otra vez en cada dispositivo.

En este entorno Tailscale aun no esta instalado: el acceso privado queda preparado,
pero no se puede activar ni verificar con un movil hasta completar esos pasos.

## Conectar Tu Gmail

1. Crea un proyecto personal en [Google Cloud Console](https://console.cloud.google.com/).
2. Activa **Gmail API** en ese proyecto.
3. Configura Google Auth Platform / la pantalla de consentimiento OAuth. Para
	 una cuenta personal, usa audiencia **External**, estado **Testing**, y anade tu
	 direccion de Gmail como usuario de prueba.
4. Configura el alcance `https://www.googleapis.com/auth/gmail.readonly`.
5. Crea un cliente OAuth de tipo **Desktop app**. Descarga su JSON y colocalo en
	 la raiz del proyecto con el nombre `credentials.json`.
6. Pulsa **Conectar Gmail** y autoriza tu cuenta en la ventana de Google.

El permiso es de solo lectura: Parcel no envia, borra ni marca correos como leidos.
Google puede mostrar una advertencia de aplicacion no verificada para tu proyecto
personal. Revisa que el proyecto sea el tuyo. En modo Testing las autorizaciones
con estos permisos normalmente caducan a los siete dias: vuelve a conectar cuando
sea necesario. Distribuir la aplicacion a terceros exige revisar los requisitos de
verificacion y uso de datos de Google; no es parte de esta version personal.

Los tokens OAuth se guardan mediante `keyring`, en el almacen de credenciales del
sistema (en Windows, Credential Manager), no en el repositorio. Desconectar elimina
la copia local. Para revocar el permiso en Google, visita
<https://myaccount.google.com/permissions>.

## Habilitar La IA

### Usar Gemini Flash

En **Conexion y privacidad**, confirma el envio de texto a Gemini y pulsa
**Aplicar modelo**. La seleccion se guarda en SQLite. Aplicar el modelo no inicia
una sincronizacion.

Los correos que fallen quedan sin procesar y pueden reintentarse con la siguiente
sincronizacion; los ya procesados correctamente no se repiten.

Gemini requiere una clave escrita directamente en `.env` y permiso explicito de
nube. No pegues la clave en el chat ni la subas a Git:

```dotenv
GEMINI_API_KEY=tu_clave_privada
GEMINI_MODEL=gemini-3.6-flash
ENABLE_CLOUD_AI=true
```

Reinicia AlPunto, selecciona Gemini Flash y confirma el envio de texto. La clave
solo existe en el servidor; el selector no la devuelve ni la guarda en SQLite.
Gemini recibe asunto, cuerpo y fecha, no adjuntos ni tokens de Gmail. Se pide
JSON estructurado sin herramientas y se conservan las comprobaciones de evidencia.

La pantalla comprueba configuracion de Gemini, no su facturacion, cuota ni validez
de la clave. Los errores se detectan al realizar una peticion.

Los mensajes largos no se truncan. Si no contienen una senal clara de recogida,
se omiten y se cuentan en el resumen; si la contienen, quedan pendientes y
muestran el asunto y el tamano para poder revisarlos.

### Gemini: Cuota Gratuita Y Condiciones

La [documentacion de facturacion](https://aistudio.google.com/docs/billing#is-Gemini-free-in-EEA-UK-CH)
indica que hay nivel gratuito disponible en Suiza. La residencia no implica un
cargo automatico: el nivel de la clave depende del proyecto al que pertenece.
Comprueba **Billing Tier** en [Google AI Studio](https://aistudio.google.com/projects).

Si no quieres pagar, utiliza solo un proyecto Free sin cuenta de facturacion
vinculada. No pulses Set up billing, no compres creditos y no uses una clave de un
proyecto de pago. La cuota gratuita es limitada; agotarla puede causar errores de
cuota. AlPunto no crea cuentas de facturacion, no aumenta cuotas ni cambia de plan.
Tampoco puede imponer un tope de gasto a una clave que ya pertenezca a un proyecto
de pago. Los presupuestos o limites con retraso no garantizan gasto cero.

Ademas del precio, revisa los [terminos de Gemini](https://aistudio.google.com/docs/terms):
incluyen requisitos sobre ofrecer aplicaciones a usuarios del EEE, Suiza o Reino
Unido y reglas de tratamiento de datos que no equivalen a su precio. No asumas
que disponer de cuota gratuita permite cualquier uso de correos personales.
Si no puedes confirmar que tu uso esta permitido y sin coste, deja Gemini
deshabilitado. Nunca utilices un proveedor para
sortear las restricciones de la organizacion en un ordenador corporativo.

## Uso

- **Sincronizar Gmail** busca avisos de paquetes en frances, ingles y espanol
	durante la ventana configurada en `SYNC_DAYS` (7 dias en la plantilla inicial),
    sin una lista cerrada de transportistas. Vinted,
	InPost, Swiss Post y Ontime no necesitan registrarse individualmente.
- Un aviso que dice explicitamente que el paquete del destinatario llego o fue
	entregado en un punto de recogida, parcel shop, locker u oficina de correos
	designada para recogerlo tambien cuenta como disponible. Las entregas a domicilio no.
- Solo se muestran recogidas disponibles. Las confirmaciones de recogida o
	devolucion pueden retirar un paquete cuando comparten identificador.
- Las fechas desconocidas se indican como tales. Los plazos vencidos siguen
	visibles con una advertencia: un plazo no confirma por si solo una devolucion.
- **Abrir mapa** abre la direccion original en Google Maps; no inventamos puntos
	ni geocodificamos la direccion por nuestra cuenta.
- **Ver documentos** abre imagenes y PDF del correo, incluidos adjuntos inline.
	No todos son QR: puede haber logos. Un PIN se muestra y se puede copiar.
- **Ya lo he recogido** retira el paquete y ofrece **Deshacer**. La accion manual
	prevalece sobre recordatorios posteriores.
- Los filtros Francia/Suiza solo incluyen paquetes cuyo pais esta identificado.
	Los de pais desconocido siguen apareciendo en **Todos**.
- Cada sincronizacion procesa hasta `SYNC_LIMIT` correos nuevos. Si quedan mas,
	pulsa de nuevo. Los correos ya procesados no vuelven a enviarse a la IA.

## Limites De Esta Primera Version

- Se ha probado con correos reales y el resultado ha sido bueno, aunque eso no
	equivale a validar todos los transportistas, idiomas y formatos posibles.
- La busqueda por palabras puede dejar fuera avisos, aunque incluya varios idiomas.
	Los terminos generales de entrega pueden incluir correos irrelevantes que luego
	se envian a la IA para filtrar. El modelo tambien puede equivocarse. Cada dato
	debe aportar una cita del correo;
	comprobar la cita reduce invenciones, pero no garantiza su interpretacion correcta.
- Se fusionan avisos con el mismo seguimiento. Sin seguimiento se usa el hilo de
	Gmail y se avisa para revisar; mensajes de distintos hilos pueden quedar duplicados,
	y una confirmacion sin identificador comun puede requerir recogida manual.
- No hay OCR de correos que solo contienen imagenes, ni lectura automatica de
	PDF por IA. Los adjuntos se pueden consultar, pero sus datos no se extraen.
- No se abren enlaces del correo, no se cargan imagenes remotas y no se entra en
	portales de transportistas. Si el QR solo existe alli, consulta el correo original.
- No se reconstruyen QR a partir de numeros ni se generan etiquetas de envio.
	La gestion de envios/devoluciones queda para una fase posterior.
- Solo sincronizacion manual, una cuenta y sin notificaciones. El acceso movil
  requiere Tailscale configurado y el PC ejecutando Parcel; no hay servicio cloud.

## Datos Y Seguridad

SQLite guarda la informacion extraida en `data/parcels.db`. Esa base de datos
contiene datos personales **sin cifrado propio**: protege tu cuenta de Windows y
el disco. No guardamos los cuerpos completos del correo; si se conserva un breve
fragmento justificativo, los campos extraidos y los identificadores de origen.
Los adjuntos se leen de Gmail bajo demanda, sin guardarse en disco por la app.

`.env`, `credentials.json`, `data/` y `.venv/` estan excluidos de Git. Para borrar
los paquetes y el historial de procesado, para el servidor y elimina `data/`.
Esto no borra el token: usa antes **Desconectar Gmail** si tambien quieres quitarlo.

Los correos se tratan como datos no confiables, nunca como instrucciones para
ejecutar acciones. La app no renderiza su HTML y el modelo no recibe herramientas.
Las acciones requieren una cabecera propia y se comprueba el origen de navegador.
En modo movil tambien se comprueba la identidad de Tailscale Serve y su URL exacta.
Todo el JavaScript, incluidos los iconos Lucide, se sirve localmente.

## Desarrollo

```powershell
uv run --group dev pytest -q
```

- `parcel_agent/gmail.py`: OAuth, busqueda, MIME y adjuntos.
- `parcel_agent/extract.py`: extraccion estructurada y comprobacion de evidencia.
- `parcel_agent/store.py`: persistencia, deduplicacion y recogida manual.
- `parcel_agent/app.py`: API local y sincronizacion en segundo plano.
- `parcel_agent/static/`: interfaz sin compilacion de frontend.

Los iconos distribuidos en `lucide.min.js` son Lucide 0.468.0, licencia ISC
(el aviso original esta incluido en el archivo). El QR de demostracion se genera
con Segno y contiene exclusivamente un texto ficticio.

La interfaz utiliza DM Sans y Sora, distribuidas bajo SIL Open Font License.
Las fuentes y sus licencias originales se incluyen en `parcel_agent/static/`;
se sirven desde el propio equipo, sin peticiones a Google Fonts al abrir Parcel.
