# app_usb · Cliente PULSIA para pendrive

**Todo lo necesario para generar el EXE está en esta carpeta.** No contiene licencias reales ni credenciales.

- `cliente.py`: interfaz Windows; consulta el servidor por HTTPS y aplica/verifica la clave recibida.
- `compilar.py`: crea un entorno aislado e invoca PyInstaller.
- `COMPILAR.bat`: compilación con doble clic en Windows.
- `config.example.json`: ejemplo público; nunca pongas aquí un token real.
- `salida/`: resultado local de compilación (excluido de Git).

## Compilar y usar

Instala Python 3.12/3.13 de 64 bits con pip y Tcl/Tk en Windows. Ejecuta `COMPILAR.bat` o el botón correspondiente en la interfaz del servidor. Se genera `salida/PULSIA_Cliente_Licencias.exe`, portable y con solicitud de permisos de administrador.

Desde el servidor, **Preparar pendrive / carpeta** copia EXE, configuración real y certificado público. Para hacerlo manualmente, copia el EXE y un `config.json` junto a él:

```json
{
  "servidor": "https://NOMBRE_O_IP_DEL_SERVIDOR:8443",
  "token": "VALOR_CLIENT_TOKEN_DE_DATOS_SERVIDOR_JSON"
}
```

Copia también la CA pública PEM como `ca.pem`. No incluyas claves privadas. El nombre/IP debe coincidir con el certificado. Si la CA ya es fiable en Windows, el cliente también usa el almacén de confianza del sistema.

El PC donde se ejecuta el EXE no necesita Python. No se buscan licencias XML en el USB ni se guardan allí las claves recibidas. La ventana muestra modelo, serie, asignación, progreso y resultado; permite seleccionar un técnico activo del servidor, detectar la edición Windows o seleccionarla y escoger tipo (CMAR, OEM, Retail…). No recibe licencias de otras ediciones o tipos como sustitución si se agota el stock solicitado. Las licencias sin clasificar no se distribuyen.

La compilación requiere Windows e Internet. Si falla, el compilador devuelve error y conserva el EXE anterior; no lo considera una compilación nueva. Los permisos de Windows o el antivirus pueden impedir reemplazar un EXE que esté abierto: ciérralo y repite.

El stock se bloquea antes de recibir la clave. Un fallo nunca libera automáticamente una asignación. Repite en el mismo PC para recuperar la misma licencia. Instalar/verificar no equivale a activar Windows.

## Dirección recordada y ventana adaptable

En el primer uso se solicita la IP o nombre del servidor. Sin puerto se utiliza HTTPS 8443; también se admite IP:puerto o URL HTTPS. La dirección queda guardada en config.json junto al EXE, conservando la credencial preparada por el servidor. Usa **Cambiar IP / servidor** para modificarla. El pendrive necesita permiso de escritura y el certificado debe corresponder a la dirección introducida. Una dirección por sí sola no sustituye el token ni la CA de la preparación del USB.

La ventana y el registro tienen barras verticales y horizontales. Al maximizar, los controles y el registro aprovechan el espacio; al reducir, las barras mantienen accesibles las zonas fuera de la vista.

## Técnicos del servidor

El campo Técnico es un desplegable de solo selección. Se carga desde el servidor al conectar y puede renovarse con **Conectar / actualizar técnicos**. Debes seleccionar un usuario activo antes de instalar. No admite escritura libre ni usuarios locales del pendrive. Si el servidor no tiene usuarios, créalos en **Usuarios / técnicos**; si no hay conexión, corrígela antes de continuar.

El servidor valida la selección al reservar. Desactivar un usuario impide que inicie nuevas operaciones, aunque aparezca en una lista cargada previamente. Actualiza también el servidor al utilizar este cliente.
