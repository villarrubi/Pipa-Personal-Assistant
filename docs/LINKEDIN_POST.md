# Post para LinkedIn

> Nota antes de publicarlo: espera a que el repositorio sea visible y exista un
> run remoto de CI verde. En este momento GitHub no inicia los jobs por una
> restricción de facturación/límite de gasto de la cuenta, no por un fallo del
> código.

He estado construyendo **Pipα**, un asistente personal local que conecta un
agente de Windows, firmware para una pantalla Waveshare ESP32-S3 y un cliente
iOS experimental.

La idea no era solo conseguir que ejecutase comandos, sino diseñar bien los
límites desde el principio:

🔒 El agente HTTP/WebSocket escucha únicamente en `127.0.0.1`.

✅ Las acciones externas requieren confirmación. WhatsApp es manual por defecto
y su envío por Cloud API es un opt-in local; Pipa no inicia llamadas de Discord
ni acepta partidas de League por su cuenta.

🔑 Las sesiones seguras usan identidades Ed25519, intercambio X25519 y cifrado
ChaCha20-Poly1305. El transporte móvil está desactivado por defecto.

🧪 Antes de compartir el repositorio he pasado una revisión local de publicación:
459 pruebas Python, análisis estático de seguridad sobre 72 módulos, cinco
variantes de firmware compiladas, smoke test del Credential Provider, auditoría
de dependencias sin vulnerabilidades conocidas y Gitleaks sobre los 231 commits
del historial.

También he reforzado la CI, los controles contra filtraciones, el README, la
guía de contribución y el checklist de publicación. Las Actions externas están
fijadas por SHA y Dependabot queda preparado para vigilar Python y GitHub
Actions.

Y, sobre todo, el estado real está documentado sin maquillaje: el hardware aún
necesita validación física, Trusted Unlock permanece desactivado y el firmware
no se considera de producción hasta validar Secure Boot, cifrado de Flash y
recuperación. El código propio se publica bajo MIT, conservando el copyright y
la citación de `villarrubi`, mientras que las dependencias mantienen sus
propios avisos.

Repositorio: https://github.com/villarrubi/Pipa-Personal-Assistant

#Python #Cybersecurity #IoT #ESP32 #Swift #Windows #BuildInPublic #SoftwareEngineering
