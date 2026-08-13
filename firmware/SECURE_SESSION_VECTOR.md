# Vector de sesión segura v2

El fixture determinista usado por Python y por el entorno PlatformIO
`secure-session-vector` usa únicamente constantes públicas de prueba. No es
una identidad del dispositivo ni una clave de producción.

El entorno incluye también el cliente de handshake X25519/Ed25519, pero el
vector determinista comprueba únicamente el record layer. Además, el
primitive `pipa_secure_audio.h/.cpp` comprueba el framing de PCM cifrado, el
AAD canónico, el orden de los bloques y el cierre fail-closed ante una
modificación. Usa el payload PCM/AAD del fixture
`mobile-ios/Tests/Fixtures/secure_audio_v2.json`, para que Python, Swift y
firmware calculen el mismo ciphertext. La identidad del agente y la
negociación completa se probarán con claves efímeras y una clave pública del
agente provisionada específicamente para la unidad de pruebas.

Para compilar el firmware que ejecutaría el vector en `setup()`:

```powershell
cd firmware
.\.venv\Scripts\platformio.exe run -e secure-session-vector
```

Al flashearlo en una placa de pruebas y abrir el monitor serie debe aparecer:

```text
secure session vector: PASS
```

La ejecución real sobre la unidad Waveshare queda pendiente hasta que llegue
el hardware. El build normal no define `PIPA_SECURE_SESSION_VECTOR_TEST` y no
ejecuta este código. Aunque el primitive se compila para detectar errores de
integración, no captura audio, no inicializa I²S/codec y no se conecta al
firmware normal.
