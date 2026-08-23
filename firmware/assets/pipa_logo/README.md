# Pipa logo

`pipa_logo_source.png` was supplied by the project owner and is used as the
full-screen display identity.

The transparent logo is converted to RGB565 by:

```powershell
python firmware/scripts/generate_logo_asset.py
```

The generated firmware asset is `firmware/src/pipa_logo_asset.h`.
