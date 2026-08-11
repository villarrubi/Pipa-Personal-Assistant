#pragma once

#include <Windows.h>
#include <ShlObj.h>
#include <credentialprovider.h>
#include "PipaCredential.h"


class PipaCredentialProvider final : public ICredentialProvider
{
public:
    PipaCredentialProvider();

    // IUnknown
    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** ppvObject
    ) override;

    ULONG STDMETHODCALLTYPE AddRef() override;
    ULONG STDMETHODCALLTYPE Release() override;

    // ICredentialProvider
    HRESULT STDMETHODCALLTYPE SetUsageScenario(
        CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
        DWORD dwFlags
    ) override;

    HRESULT STDMETHODCALLTYPE SetSerialization(
        const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs
    ) override;

    HRESULT STDMETHODCALLTYPE Advise(
        ICredentialProviderEvents* pcpe,
        UINT_PTR upAdviseContext
    ) override;

    HRESULT STDMETHODCALLTYPE UnAdvise() override;

    HRESULT STDMETHODCALLTYPE GetFieldDescriptorCount(
        DWORD* pdwCount
    ) override;

    HRESULT STDMETHODCALLTYPE GetFieldDescriptorAt(
        DWORD dwIndex,
        CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd
    ) override;

    HRESULT STDMETHODCALLTYPE GetCredentialCount(
        DWORD* pdwCount,
        DWORD* pdwDefault,
        BOOL* pbAutoLogonWithDefault
    ) override;

    HRESULT STDMETHODCALLTYPE GetCredentialAt(
        DWORD dwIndex,
        ICredentialProviderCredential** ppcpc
    ) override;

private:
    ~PipaCredentialProvider();

    LONG _refCount;
    CREDENTIAL_PROVIDER_USAGE_SCENARIO _usageScenario;
    PipaCredential* _credential;
};