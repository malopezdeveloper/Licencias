# PULSIA · Servidor de licencias CMAR

Servidor LAN con **interfaz gráfica de escritorio**, stock XML centralizado y un cliente portable Windows que se ejecuta desde el pendrive. Versión 0.6.

## Qué puedes hacer desde la interfaz

- **Stock:** importar XML sueltos, ZIP o carpetas completas con subcarpetas, detectar claves duplicadas, buscar y filtrar, retirar o habilitar licencias sin borrar su historial, exportar CSV y hacer copias de seguridad.
- **Stock por tipo:** resumen por edición (Pro, Home…) y tipo (CMAR, OEM, Retail…), con cantidades disponibles, usadas, pendientes, en revisión, retiradas y sin identificar.
- **Instalaciones:** consultar número de serie, fabricante, modelo, Windows y build, UUID, IP, técnico seleccionado del servidor, fechas, resultado, últimos cinco caracteres de las claves anterior y nueva, código de Windows e historial. Dar de baja una asignación con motivo para devolver la licencia al stock.
- **Usuarios / técnicos:** añadir usuarios, cambiar sus nombres, activar o desactivar y consultar su número de instalaciones. Solo los activos aparecen en el cliente.
- **Historial:** consultar importaciones, asignaciones, resultados y bajas. Actualización automática cada tres segundos.
- **Servidor y app USB:** configurar HTTPS, crear certificados LAN, iniciar/detener el servidor, compilar el EXE y preparar el pendrive con sus tres archivos.

Las licencias con edición o tipo sin identificar se conservan fuera del stock distribuible hasta que las clasifiques. Los XML se guardan en SQLite. Una transacción bloquea la licencia **antes** de entregarla. Solicitudes simultáneas no pueden recibir la misma licencia y repetir desde un PC recupera su asignación activa. Pendientes y revisión siguen bloqueadas; no caducan ni se liberan automáticamente.

## Arranque en Windows

1. Descarga este repositorio y extrae el ZIP.
2. Instala **Python 3.12 o 3.13 de 64 bits**, con pip y Tcl/Tk, desde [python.org](https://www.python.org/downloads/windows/).
3. Ejecuta **INICIAR_SERVIDOR.bat**. El primer arranque crea `.venv` e instala la dependencia para generar certificados; necesita Internet solo para esa preparación.
4. En **Servidor y app USB**, indica la URL que usarán los clientes: por ejemplo `https://192.168.1.139:8443`, usando la IP real y estable de tu servidor. También puedes usar un nombre que resuelva por DNS.
5. Pulsa **Crear certificados LAN**. El certificado se genera para el nombre o IP de esa URL. Si cambias el nombre/IP, crea nuevos certificados y vuelve a preparar los USB.
6. Pulsa **Iniciar servidor** y permite TCP 8443 entrante en el firewall de la LAN del taller. Mantén abierta la aplicación; no se instala como servicio automático.
7. En **Usuarios / técnicos**, crea los usuarios que podrán seleccionarse en el cliente. La lista comienza vacía; no se inventan usuarios al migrar.
8. En **Stock**, importa los XML que todavía no están consumidos: selecciona archivos XML/ZIP o una carpeta. Comprueba y completa su clasificación antes de distribuirlos.

Si ya tienes certificados de tu organización, selecciónalos en lugar de crearlos. Necesitas certificado servidor y clave privada PEM, además de la CA pública PEM para los USB. Nunca se desactiva la comprobación TLS.

## Importación y clasificación

En **Stock** puedes seleccionar uno o varios XML/ZIP juntos, o una carpeta con sus subcarpetas. Los ZIP se leen en memoria, sin extraerlos al disco, y pueden contener XML en subcarpetas. No se abren ZIP anidados dentro de otros ZIP. Otros tipos de archivo se ignoran. Se informa de importados, duplicados y errores; un XML incorrecto no impide leer los siguientes. Reimportar nunca duplica claves ni devuelve usadas al stock.

La clasificación guarda **dos campos separados**: edición Windows (Pro, Home, Enterprise…) y tipo de licencia (CMAR, OEM, Retail, Volumen…). Por ejemplo, **Pro / CMAR** es una combinación válida.

1. Si el XML declara `Edition`, `EditionID`, `ProductName`, `Channel` o `LicenseType`, se reconocen los valores explícitos compatibles. Los metadatos contradictorios requieren revisión.
2. Si solo contiene `ProductKey`, `ProductKeyID`, `ProductKeyState` y `ProductKeyPartNumber`, estos campos **no permiten deducir con certeza** Pro/Home/CMAR. Ni el nombre del archivo ni un estado numérico se interpretan como edición o tipo.
3. Selecciona la licencia y pulsa **Ver / clasificar licencia**. Asigna la edición y el tipo indicados por el proveedor. Si tiene referencia, activa **Aplicar a todas con esta referencia y recordar para futuras importaciones**: clasifica el lote existente y las futuras importaciones con esa misma referencia. Las reglas se guardan en la base local; no se publican.
4. Si no hay referencia, puedes clasificar cada licencia individualmente. Las clasificaciones manuales se conservan al reiniciar. **Sin identificar** no se asigna automáticamente a ningún PC.

El estado numérico original del XML se muestra en la ficha como **Estado XML**, separado de los estados administrativos pendiente/usada/baja. La importación valida estructura y formato; no consulta Microsoft ni certifica autenticidad, activación, edición real o derecho de reutilización.

Límites por operación: 1 MiB por XML, 10.000 XML y 256 MiB leídos; máximo 20.000 entradas por ZIP. Se rechazan XML cifrados dentro de ZIP, rutas no admitidas, enlaces simbólicos y DTD/entidades. Divide lotes mayores.

## Ventanas y desplazamiento

Servidor y cliente incluyen barras horizontales y verticales para acceder al contenido en ventanas pequeñas. Al ampliar o maximizar, las tablas y registros ocupan el espacio disponible; los contadores del servidor se redistribuyen en filas según el ancho. Las tablas mantienen su posición de desplazamiento al actualizarse. Los registros y las fichas de detalle tienen sus propias barras para líneas largas. La rueda desplaza el contenido; Mayús + rueda permite desplazamiento horizontal en el contenedor general.

## Crear el EXE y preparar el pendrive

Todo el código y el compilador del cliente están en **app_usb/** dentro de la carpeta del servidor.

1. En Windows, pulsa **Compilar EXE del cliente** desde la interfaz. También puedes ejecutar **app_usb/COMPILAR.bat**. La primera compilación necesita Internet para instalar PyInstaller en su propio entorno.
2. El resultado es `app_usb/salida/PULSIA_Cliente_Licencias.exe`.
3. Pulsa **Preparar pendrive / carpeta** y selecciona una carpeta del USB. Se copian el EXE, `config.json` con URL/token y `ca.pem` con el certificado público. No se copian licencias, bases ni claves privadas.
4. En cada PC, abre **PULSIA_Cliente_Licencias.exe**, acepta los permisos de administrador, conecta y selecciona un técnico de la lista del servidor, elige edición automática o explícita y el tipo deseado (por ejemplo CMAR), y pulsa **Solicitar e instalar licencia**. En automático se consulta `EditionID` del Windows instalado. El servidor solo ofrece stock de esa edición y del tipo solicitado; no sustituye Home por Pro ni cambia de tipo si no hay existencias.

En el primer arranque, el cliente **pregunta la IP o nombre del servidor**. Puedes introducir `192.168.1.139`, `192.168.1.139:9443` o una URL HTTPS. Una dirección sin puerto utiliza 8443. Se guarda junto al EXE en `config.json`, conservando el token y el resto de ajustes. En los siguientes arranques se recuerda; **Cambiar IP / servidor** permite modificarla. El USB debe permitir escritura. Si falla el guardado, se informa y se conserva la configuración anterior. Cambiar la dirección se bloquea mientras hay una instalación en curso.

La IP o nombre introducidos deben estar incluidos en el certificado del servidor. Si cambias a una dirección nueva, genera un certificado para esa dirección desde el servidor y vuelve a preparar el USB con su CA pública. No se omite la verificación TLS ni se envía el token por HTTP.

Los PCs clientes no necesitan Python. El USB solo transporta el cliente, su configuración y el certificado. La asignación pertenece al **PC**, no al pendrive. No se necesita la antigua carpeta `220`, `lic2.ps1` ni `START2.bat`.

En [Actions](https://github.com/malopezdeveloper/Licencias/actions), el flujo **Validar y compilar cliente Windows** también prueba la interfaz y compila el EXE. Una ejecución completada permite descargar el artefacto `PULSIA_Cliente_Licencias_Windows_x64`. Su configuración es de ejemplo: personalízala con el servidor o prepara el USB desde la interfaz. El ejecutable no está firmado digitalmente.

## Estructura

| Ruta | Contenido |
|---|---|
| `servidor_gui.py` | Aplicación gráfica de administración |
| `servidor.py` | Stock, SQLite y API HTTPS |
| `certificados.py` | Generación de CA local y certificado servidor |
| `INICIAR_SERVIDOR.bat` | Arranque Windows y preparación del entorno |
| `app_usb/` | Cliente, configuración de ejemplo y compilador del EXE |
| `tests/` | Pruebas de concurrencia, importación ZIP/carpetas, clasificación, migración, HTTPS, interfaz y cliente |
| `datos/` | Base, configuración y certificados locales; excluidos de Git |

## Técnicos proporcionados por el servidor

El técnico es obligatorio y **no se puede escribir libremente** en el cliente. Al abrir el cliente con una dirección confirmada, o al cambiarla, se conecta por HTTPS y obtiene los usuarios activos del servidor. También hay un botón **Conectar / actualizar técnicos**. El botón de instalación se habilita después de seleccionar uno.

Desde **Usuarios / técnicos** puedes añadir usuarios, cambiar sus nombres y activarlos/desactivarlos. El servidor valida el ID del técnico activo en la misma transacción que reserva la licencia: nombres inventados, IDs desconocidos, usuarios inactivos y clientes antiguos que no envían selección se rechazan sin consumir stock. Una lista antigua del USB no permite usar un técnico que ya se haya desactivado.

Cada instalación guarda el ID estable y el nombre del técnico que inicia o retoma su asignación pendiente. Si otro usuario retoma una operación pendiente, queda como responsable y el historial conserva el operador anterior. Cuando la instalación ya está usada, los reintentos no cambian su responsable histórico. Cambiar el nombre o desactivarlo no modifica las instalaciones antiguas. Los reintentos y confirmaciones registran el operador en el historial; una operación ya iniciada puede confirmar su resultado aunque el usuario se desactive mientras instala. Los usuarios se desactivan en lugar de borrar su historial.

La lista es un catálogo para identificar al operador, no un inicio de sesión con contraseña. Su modificación se hace en el servidor, no desde la API del pendrive. Si no hay usuarios activos o falla la conexión, el cliente no permite escribir otro nombre ni iniciar una instalación.

**Al actualizar a v0.6:** sustituye el código del servidor conservando `datos/`, crea los usuarios y recompila/prepara los USB. Los registros anteriores se conservan con su nombre histórico; no se crean usuarios automáticamente a partir de esos nombres. Debes actualizar tanto el servidor como los clientes.

## Datos y copias de seguridad

`datos/licencias.db` contiene los XML completos, asignaciones y eventos. `datos/servidor.json` contiene la credencial cliente y la configuración. Los certificados creados se guardan en `datos/certificados/`. Cada generación crea una CA nueva y conserva las anteriores; no se conserva la clave privada de la CA, que no hace falta para usar el certificado emitido.

**No subas datos reales al repositorio público.** `.gitignore` excluye bases, XML, credenciales, certificados, claves, entornos y ejecutables generados. La configuración publicada en `app_usb/config.example.json` es ficticia; las credenciales se crean localmente. Protege la carpeta `datos` con permisos del sistema para los administradores y la cuenta que ejecuta el servidor. Trata el token del USB como credencial del taller y no expongas la API a Internet.

La copia desde la interfaz es una instantánea consistente de SQLite, incluso con servidor activo. Conserva aparte `servidor.json` y los certificados. Para restaurar, cierra el servidor y sustituye la base por la copia. Si la copia es antigua, reconcilia primero las asignaciones posteriores: de lo contrario podrían volver a ofrecerse claves ya entregadas.

Para migrar de v0.1, **con el servidor antiguo detenido**, copia su `licencias.db` y `servidor.json` dentro de `datos/` antes del primer arranque. La estructura se actualiza conservando licencias y asignaciones. Completa la configuración HTTPS en la interfaz y prepara los USB.

## Comportamiento y límites

- Se instala mediante `SoftwareLicensingService.InstallProductKey` y se verifica el sufijo entre productos de Windows. Se registra el estado de licencia que devuelve Windows, pero **no se ejecuta la activación** (`/ato`). Verificar cinco caracteres conserva la limitación del script original: dos claves pueden compartir sufijo.
- Si falla la red o el proceso, la licencia puede permanecer pendiente. Reintenta **en el mismo PC**; no se consume otra. Si Windows ya tenía la clave instalada, el reintento permite repetir la comprobación y notificación.
- La baja es administrativa: devuelve al stock, conserva el historial y **no desinstala** la clave del PC anterior. Verifica que procede reutilizarla antes de darla de baja.
- El UUID viene del firmware. Equipos con UUID duplicados se identificarían como el mismo PC; corrige esos UUID antes de usar la aplicación. Se rechazan los UUID nulos y genéricos de unos.
- Los XML `BURN` y las claves duplicadas se omiten. El sistema no puede detectar uso previo fuera de este stock; no vuelvas a usar las copias originales en otros scripts o servidores.
- La edición de Windows debe ser compatible con la clave. Con un cliente antiguo, el servidor usa el nombre de Windows o una única edición identificada del stock para compatibilidad; si hay ambigüedad rechaza la petición y pide actualizar el cliente.
- El cliente necesita permisos de administrador y los componentes CIM/licencias de Windows operativos.
- No hay administración remota ni autenticación de usuarios en la interfaz: quien puede abrir la aplicación en el servidor puede administrar el stock. La API LAN requiere el token y TLS.

## Linux

El servidor gráfico también puede ejecutarse en Linux **con escritorio**, Python 3 y Tk disponibles:

```sh
sh iniciar_servidor.sh
```

En Debian/Ubuntu instala previamente `python3-venv` y `python3-tk`. También existe el modo sin interfaz `python servidor.py --servir`, después de configurar certificados y red. El cliente y su compilación son para Windows.

## Pruebas

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

La prueba gráfica necesita escritorio (o Xvfb en Linux). Las pruebas del cliente simulan cambios de licencia; no aplican claves en el PC de pruebas. El flujo Windows compila el ejecutable nativo, pero la instalación de una licencia real debe validarse en un equipo del taller destinado a esa licencia.
