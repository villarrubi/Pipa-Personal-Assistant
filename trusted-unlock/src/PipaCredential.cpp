#include "../include/PipaCredential.h"

#include <combaseapi.h>
#include <shlwapi.h>


namespace
{
// This provider is intentionally inert until a separately reviewed unlock
// design exists. Changing this requires changing the compile-time invariant
// below as well as the security review.
constexpr bool kTrustedUnlockEnabled = false;
static_assert(
    !kTrustedUnlockEnabled,
    "Trusted Unlock must remain disabled in this provider"
);
}


enum PIPA_FIELD_ID
{
    PFI_TITLE = 0,
    PFI_STATUS = 1,
    PFI_COUNT = 2
};


PipaCredential::PipaCredential()
    : _refCount(1)
{
}


PipaCredential::~PipaCredential()
{
}


HRESULT STDMETHODCALLTYPE PipaCredential::QueryInterface(
    REFIID riid,
    void** ppvObject
)
{
    if (ppvObject == nullptr)
        return E_POINTER;

    *ppvObject = nullptr;

    if (
        riid == IID_IUnknown ||
        riid == IID_ICredentialProviderCredential
    )
    {
        *ppvObject =
            static_cast<ICredentialProviderCredential*>(this);

        AddRef();
        return S_OK;
    }

    return E_NOINTERFACE;
}


ULONG STDMETHODCALLTYPE PipaCredential::AddRef()
{
    return InterlockedIncrement(&_refCount);
}


ULONG STDMETHODCALLTYPE PipaCredential::Release()
{
    LONG count = InterlockedDecrement(&_refCount);

    if (count == 0)
    {
        delete this;
        return 0;
    }

    return count;
}


HRESULT STDMETHODCALLTYPE PipaCredential::Advise(
    ICredentialProviderCredentialEvents*
)
{
    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredential::UnAdvise()
{
    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredential::SetSelected(
    BOOL* pbAutoLogon
)
{
    if (pbAutoLogon == nullptr)
        return E_POINTER;

    // MUY IMPORTANTE:
    // todavía no permitimos ningún inicio automático.
    *pbAutoLogon = FALSE;

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredential::SetDeselected()
{
    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetFieldState(
    DWORD dwFieldID,
    CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis
)
{
    if (pcpfs == nullptr || pcpfis == nullptr)
        return E_POINTER;

    switch (dwFieldID)
    {
        case PFI_TITLE:
            *pcpfs = CPFS_DISPLAY_IN_SELECTED_TILE;
            *pcpfis = CPFIS_NONE;
            return S_OK;

        case PFI_STATUS:
            *pcpfs = CPFS_DISPLAY_IN_SELECTED_TILE;
            *pcpfis = CPFIS_NONE;
            return S_OK;

        default:
            return E_INVALIDARG;
    }
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetStringValue(
    DWORD dwFieldID,
    PWSTR* ppwsz
)
{
    if (ppwsz == nullptr)
        return E_POINTER;

    *ppwsz = nullptr;

    PCWSTR value = nullptr;

    switch (dwFieldID)
    {
        case PFI_TITLE:
            value = L"Pip\u03B1 Trusted Unlock";
            break;

        case PFI_STATUS:
            value = L"Desactivado: no autentica";
            break;

        default:
            return E_INVALIDARG;
    }

    return SHStrDupW(value, ppwsz);
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetBitmapValue(
    DWORD,
    HBITMAP*
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetCheckboxValue(
    DWORD,
    BOOL*,
    PWSTR*
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetSubmitButtonValue(
    DWORD,
    DWORD*
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetComboBoxValueCount(
    DWORD,
    DWORD*,
    DWORD*
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetComboBoxValueAt(
    DWORD,
    DWORD,
    PWSTR*
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::SetStringValue(
    DWORD,
    PCWSTR
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::SetCheckboxValue(
    DWORD,
    BOOL
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::SetComboBoxSelectedValue(
    DWORD,
    DWORD
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::CommandLinkClicked(
    DWORD
)
{
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredential::GetSerialization(
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon
)
{
    if (
        pcpgsr == nullptr ||
        pcpcs == nullptr ||
        ppwszOptionalStatusText == nullptr ||
        pcpsiOptionalStatusIcon == nullptr
    )
    {
        return E_POINTER;
    }

    // Pipα no entrega ninguna credencial a Windows mientras Trusted Unlock
    // permanezca desactivado. La serializacion se deja completamente vacia.
    *pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED;

    ZeroMemory(
        pcpcs,
        sizeof(CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION)
    );

    *ppwszOptionalStatusText = nullptr;
    *pcpsiOptionalStatusIcon = CPSI_NONE;

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredential::ReportResult(
    NTSTATUS,
    NTSTATUS,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon
)
{
    if (ppwszOptionalStatusText != nullptr)
        *ppwszOptionalStatusText = nullptr;

    if (pcpsiOptionalStatusIcon != nullptr)
        *pcpsiOptionalStatusIcon = CPSI_NONE;

    return S_OK;
}
