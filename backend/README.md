# Pipα Core

Este módulo contiene el núcleo de sesiones y protocolo del asistente. En esta
fase vive dentro del Windows Agent y expone el WebSocket local `/pipa/ws`.

## Flujo autenticado

1. El dispositivo ya emparejado solicita `POST /pipa/challenge` con su
   `device_id`.
2. Firma el objeto `challenge` con su clave Ed25519 privada.
3. Abre `/pipa/ws` y envía `hello` con `device_id`, `challenge_id` y
   `signature`.
4. Después puede enviar `text_input`, `tool_call`, `confirm` y eventos de
   interacción.

La clave privada nunca se guarda en este repositorio ni en Windows. El agente
solo acepta conexiones WebSocket locales mientras no exista un transporte
remoto diseñado y protegido.

## Confirmaciones

Las herramientas marcadas como `unsafe` no se ejecutan al primer mensaje. El
dispositivo recibe `confirm_request` y debe contestar con `confirm` antes de
que se abra una aplicación, una URL, Discord, WhatsApp, League o se bloquee el
ordenador.

El adaptador de frases actual es deliberadamente pequeño y determinista. La
integración de STT/LLM/TTS se añadirá sobre este contrato, no dentro de los
handlers de Windows.

La memoria actual es acotada y vive solo en el proceso: `remember_fact` y
`recall_memory` permiten probar preferencias sin crear una base de datos con
datos personales antes de definir cifrado, borrado y exportación.

## Simulador

Desde la raíz del repositorio:

```powershell
python backend/pipa_simulator.py
```

El simulador genera una identidad efímera, realiza el desafío/respuesta y
ejecuta un `tool_call` de prueba. No escribe claves ni modifica Windows.
