# Usuarios de prueba y registro de colaboradores

Actualizado: 24 de octubre de 2026. Prototipo local: http://localhost:8084.

## Cuentas de prueba solicitadas

| Perfil | Correo de acceso | Alcance |
|---|---|---|
| Trabajador | trabajador.prueba@geocattle.local | Predio del dueño del prototipo; consulta y reportes sujetos al flujo de aprobación |
| Veterinario | veterinario.prueba@geocattle.local | Mismo predio; fichas técnicas, sanitarias y agenda con autoría |
| Administrador | admin.prueba@geocattle.local | Panel global y soporte; debe configurar TOTP antes de acceder |

Las contraseñas únicas se entregaron al solicitante y quedaron en `.runtime/accesos_prueba_roles.json`, excluido de Git. No se incluyen en esta guía. Se validó el inicio de sesión de los colaboradores y que no puedan invitar a terceros; el administrador requiere configurar MFA antes de obtener sesión. No se creó un predio, bovino ni lectura ficticia en la base operativa.

Las cuentas son nuevas y están identificadas como prueba. El alta local solicitada conserva invitaciones aceptadas para trabajador/veterinario, vínculo con el dueño del predio, membresías y auditoría de provisión técnica; no modifica la contraseña o MFA del dueño. Esa provisión puntual no añade un registro público ni cambia el flujo normal descrito abajo.

## Quién registra a cada persona

- El administrador de plataforma da de alta las cuentas de dueños/clientes. Su propio alta inicial es una operación explícita de administración local; no hay registro público de administradores.
- **El dueño invita a trabajadores y veterinarios** al predio seleccionado. El destinatario activa su identidad y contraseña mediante la invitación. No puede elegir un rol o predio diferente durante la aceptación.
- El administrador en soporte conserva la consulta y gestión autorizada de colaboradores ya incorporados; la creación de invitaciones nuevas corresponde al dueño.
- Los trabajadores y veterinarios no pueden registrar colaboradores.

## Paso a paso del dueño

1. Iniciar sesión con la cuenta de dueño y seleccionar el predio correcto.
2. Si aún no tiene segundo factor, abrir **Mi perfil → Activar doble verificación**, confirmar la contraseña y configurar una aplicación autenticadora TOTP. Conservar esa configuración; la aplicación pide un código nuevo al verificar operaciones.
3. Entrar a **Equipo y permisos** y verificar contraseña y código TOTP para abrir la gestión del equipo.
4. Pulsar **Invitar usuario**, escribir el correo y elegir **Trabajador** o **Veterinario**.
5. Confirmar el correo, perfil y predio. Introducir contraseña y un código TOTP nuevo para crear esa invitación exacta. Si acaba de usar un código, esperar al siguiente de la aplicación autenticadora.
6. Copiar el enlace de enrolamiento y entregarlo al destinatario. **El prototipo no envía correo automáticamente.** El enlace dura 48 horas y se utiliza una sola vez.
7. Consultar **Colaboradores del predio** para comprobar la incorporación. Desde allí se puede modificar o revocar el acceso manteniendo su historial.

## Paso a paso de la persona invitada

1. Abrir el enlace en una sesión propia; para probar varios roles en el mismo PC conviene una ventana privada o cerrar antes la sesión del dueño.
2. Revisar el correo, rol, predio y vencimiento mostrados en la invitación.
3. Si es una cuenta nueva, escribir nombre y definir una contraseña de al menos doce caracteres. Si el correo ya tiene cuenta, utilizar su contraseña actual; aceptar otro predio no cambia la contraseña ni el nombre existentes.
4. Aceptar e iniciar sesión con el correo exacto de la invitación y su contraseña. Los datos visibles corresponden a los predios con membresía vigente.

Un enlace usado, revocado o vencido no activa acceso. Si vence, el dueño genera otro. El enlace local `localhost` sirve para pruebas en este PC; en un despliegue para otros equipos debe emplearse la dirección real de la aplicación.

## Diferencia entre perfiles

| Acción | Dueño | Trabajador | Veterinario | Administrador |
|---|---|---|---|---|
| Invitar trabajador/veterinario | Sí, en su predio y con MFA | No | No | No; administra colaboradores ya incorporados |
| Consultar mapa, bovinos y sensores | Sus predios | Predios autorizados | Predios autorizados | Contexto de soporte seleccionado |
| Administrar collar y geocerca | Sí | No | No | Soporte autorizado |
| Registro sanitario | Directo | Propuesta por defecto; confianza por acción | Directo con autoría | Soporte autorizado |
| Aprobar propuestas y conceder confianza | Sí | No | No | Soporte autorizado y MFA donde corresponda |
| Panel global de clientes y KPI | No | No | No | Sí, MFA obligatorio |

Las cuentas de prueba no incluyen confianza directa concedida al trabajador. El propietario puede concederla por acción cuando quiera probar ese flujo; no se activa de forma automática.

## Verificación de esta actualización

- 95 pruebas de backend correctas, incluidas15 verificaciones nuevas de invitaciones, roles, vigencia y conservación de identidades. Registro: `.runtime/review/backend-tests-2026-10-24.txt`.
- TypeScript y compilación Vite correctos. La API operativa contiene `/api/v1/v3/enrol/preview` y se verificaron las tres credenciales después del reinicio confirmado por el usuario.
- Comprobación visual aislada de cuenta nueva, cuenta existente y enlace inválido. La API temporal de QA quedó cerrada y no se aceptaron estas invitaciones de muestra en el predio real.
- [Cuenta nueva](evidencias/registro-2026-10-24/GeoCattle-invitacion-nueva-QA.png), [cuenta existente](evidencias/registro-2026-10-24/GeoCattle-invitacion-existente-QA.png) e [invitación inválida](evidencias/registro-2026-10-24/GeoCattle-invitacion-invalida-QA.png).
