#include "../include/PipaCredentialProvider.h"

#include <shlwapi.h>


PipaCredentialProvider::PipaCredentialProvider()
    : _refCount(1),
      _usageScenario(CPUS_INVALID),
      _credential(new PipaCredential())
{
}


PipaCredentialProvider::~PipaCredentialProvider()
{
    if (_credential != nullptr)
    {
        _credential->Release();
        _credential = nullptr;
    }
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::QueryInterface(
    REFIID riid,
    void** ppvObject
)
{
    if (ppvObject == nullptr)
    {
        return E_POINTER;
    }

    *ppvObject = nullptr;

    if (
        riid == IID_IUnknown ||
        riid == IID_ICredentialProvider
    )
    {
        *ppvObject = static_cast<ICredentialProvider*>(this);
        AddRef();

        return S_OK;
    }

    return E_NOINTERFACE;
}


ULONG STDMETHODCALLTYPE PipaCredentialProvider::AddRef()
{
    return InterlockedIncrement(&_refCount);
}


ULONG STDMETHODCALLTYPE PipaCredentialProvider::Release()
{
    LONG count = InterlockedDecrement(&_refCount);

    if (count == 0)
    {
        delete this;
        return 0;
    }

    return count;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::SetUsageScenario(
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
    DWORD dwFlags
)
{
    UNREFERENCED_PARAMETER(dwFlags);

    switch (cpus)
    {
        case CPUS_LOGON:
        case CPUS_UNLOCK_WORKSTATION:
            _usageScenario = cpus;
            return S_OK;

        default:
            return E_NOTIMPL;
    }
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::SetSerialization(
    const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs
)
{
    UNREFERENCED_PARAMETER(pcpcs);

    // Nunca aceptamos una serializacion externa para convertirla en un
    // desbloqueo. Trusted Unlock sigue siendo solo una tile inerte.
    return E_NOTIMPL;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::Advise(
    ICredentialProviderEvents* pcpe,
    UINT_PTR upAdviseContext
)
{
    UNREFERENCED_PARAMETER(pcpe);
    UNREFERENCED_PARAMETER(upAdviseContext);

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::UnAdvise()
{
    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::GetFieldDescriptorCount(
    DWORD* pdwCount
)
{
    if (pdwCount == nullptr)
    {
        return E_POINTER;
    }

    *pdwCount = 2;

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::GetFieldDescriptorAt(
    DWORD dwIndex,
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd
)
{
    if (ppcpfd == nullptr)
    {
        return E_POINTER;
    }

    *ppcpfd = nullptr;

    static const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR descriptors[] =
    {
        {
            0,
            CPFT_LARGE_TEXT,
            const_cast<PWSTR>(L"Pip\u03B1 Trusted Unlock"),
            GUID_NULL
        },
        {
            1,
            CPFT_SMALL_TEXT,
            const_cast<PWSTR>(L"Estado"),
            GUID_NULL
        }
    };

    if (dwIndex >= 2)
    {
        return E_INVALIDARG;
    }

    auto* descriptor =
        static_cast<CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*>(
            CoTaskMemAlloc(
                sizeof(CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR)
            )
        );

    if (descriptor == nullptr)
    {
        return E_OUTOFMEMORY;
    }

    *descriptor = descriptors[dwIndex];

    descriptor->pszLabel = nullptr;

    HRESULT hr = SHStrDupW(
        descriptors[dwIndex].pszLabel,
        &descriptor->pszLabel
    );

    if (FAILED(hr))
    {
        CoTaskMemFree(descriptor);
        return hr;
    }

    *ppcpfd = descriptor;

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::GetCredentialCount(
    DWORD* pdwCount,
    DWORD* pdwDefault,
    BOOL* pbAutoLogonWithDefault
)
{
    if (
        pdwCount == nullptr ||
        pdwDefault == nullptr ||
        pbAutoLogonWithDefault == nullptr
    )
    {
        return E_POINTER;
    }

    *pdwCount = 1;
    *pdwDefault = 0;
    *pbAutoLogonWithDefault = FALSE;

    return S_OK;
}


HRESULT STDMETHODCALLTYPE PipaCredentialProvider::GetCredentialAt(
    DWORD dwIndex,
    ICredentialProviderCredential** ppcpc
)
{
    if (ppcpc == nullptr)
    {
        return E_POINTER;
    }

    *ppcpc = nullptr;

    if (dwIndex != 0 || _credential == nullptr)
    {
        return E_INVALIDARG;
    }

    return _credential->QueryInterface(
        IID_ICredentialProviderCredential,
        reinterpret_cast<void**>(ppcpc)
    );
}
