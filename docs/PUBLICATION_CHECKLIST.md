# Checklist para publicar Pipα

Esta lista separa lo automatizable de las decisiones y ajustes del alojamiento
que no puede imponer el código del repositorio.

## Bloqueantes antes de hacerlo público

- [x] Elegir una licencia compatible con la intención del proyecto y añadirla
  como `LICENSE`. El código propio usa MIT y conserva el copyright de
  `villarrubi`; las dependencias mantienen sus licencias independientes.
- [x] Añadir `CITATION.cff` para que GitHub ofrezca una cita y el crédito del
  autor sea visible al reutilizar el proyecto.
- [ ] Confirmar que el nombre, logotipo y textos no infringen marcas o derechos
  de terceros.
- [x] Auditar el árbol y los 231 commits con Gitleaks y los comprobadores del
  proyecto: no se han detectado secretos. Si el propietario recuerda algún
  secreto real que no haya sido detectado, debe revocarlo igualmente.
- [x] El propietario acepta que el correo histórico del autor aparezca
  públicamente; los commits existentes no se reescriben.
- [ ] Resolver el bloqueo de facturación/límite de gasto de GitHub Actions o
  cambiar el repositorio a público y relanzar CI. Los jobs remotos actuales no
  llegan a iniciarse por esa restricción de cuenta; una validación local verde
  no sustituye un run remoto verde desde un checkout limpio. La sesión local
  de `gh` está caducada; después de autenticarla con `gh auth login -h github.com`
  hay que revisar facturación/visibilidad y relanzar el workflow.
- [x] Ejecutar la compuerta completa de software:

```powershell
.\scripts\pipa_preflight.ps1 `
  -SkipStartupCheck -CheckFirmware -CheckCredentialProvider
git diff --check
git status --short
```

- [x] Ejecutar Gitleaks 8.30.1 o posterior contra todo el historial. La CI
  incluye esta compuerta y `.gitleaks.toml` solo permite valores deterministas
  exactos de los vectores de prueba y nombres de tipos criptográficos.

- [ ] Si se van a distribuir binarios de firmware, generar y archivar un SBOM
  y los textos de licencia de las versiones realmente resueltas. El aviso de
  fuente en `firmware/THIRD_PARTY_NOTICES.md` documenta las dependencias
  directas, pero no sustituye la revisión de los componentes transitivos de
  Arduino-ESP32/ESP-IDF ni de sus obligaciones LGPL.

- [x] Revisar los archivos ignorados actuales: solo queda `apps.json` como
  configuración local no generada, correctamente excluida; entornos, builds,
  cachés y credenciales de dispositivo siguen fuera del inventario publicable.

## Configuración recomendada en GitHub

- [ ] Activar **Private vulnerability reporting** en Security.
- [ ] Activar Dependabot alerts y security updates. El repositorio incluye
  `.github/dependabot.yml` para Python y GitHub Actions.
- [ ] Proteger la rama principal: exigir pull request, CI correcta y bloqueo de
  force-push y borrado.
- [ ] Activar secret scanning y push protection si están disponibles.
- [ ] Comprobar que los permisos predeterminados de GitHub Actions sean de solo
  lectura. El workflow ya declara `contents: read`.
- [ ] Añadir una descripción corta, temas y URL de documentación sin incluir
  datos personales.

## Comprobaciones de alcance

- [x] El README sigue indicando que es un prototipo y que el hardware no está
  validado.
- [x] Trusted Unlock permanece desactivado y no entrega credenciales.
- [x] El transporte móvil permanece opt-in y restringido a una IP local
  concreta.
- [x] No se presenta la imagen de firmware actual como producción: faltan
  Secure Boot, cifrado de Flash, anti-rollback y validación física.
- [x] WhatsApp conserva el modo manual por defecto y el modo Cloud API exige
  configuración local y confirmación; Discord, League y música conservan el
  último paso manual documentado.

## Después de publicar

- [ ] Confirmar que la CI completa pasa desde un checkout limpio.
- [ ] Abrir los enlaces del README y comprobar la presentación en GitHub.
- [ ] Crear una release solo después de documentar cambios, artefactos y
  limitaciones. No adjuntar DLL, firmware o app firmada sin un proceso de
  procedencia, firma y recuperación revisado.
- [ ] Revisar periódicamente alertas, dependencias y límites de seguridad; una
  ejecución antigua de CI no certifica versiones futuras.
