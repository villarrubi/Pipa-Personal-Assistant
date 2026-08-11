#pragma once

#include <Windows.h>
#include <credentialprovider.h>

class PipaCredential final : public ICredentialProviderCredential
{
public:
    PipaCredential();

    // IUnknown
    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** ppvObject
    ) override;

    ULONG STDMETHODCALLTYPE AddRef() override;
    ULONG STDMETHODCALLTYPE Release() override;

    // ICredentialProviderCredential
    HRESULT STDMETHODCALLTYPE Advise(
        ICredentialProviderCredentialEvents* pcpce
    ) override;

    HRESULT STDMETHODCALLTYPE UnAdvise() override;

    HRESULT STDMETHODCALLTYPE SetSelected(
        BOOL* pbAutoLogon
    ) override;

    HRESULT STDMETHODCALLTYPE SetDeselected() override;

    HRESULT STDMETHODCALLTYPE GetFieldState(
        DWORD dwFieldID,
        CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
        CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis
    ) override;

    HRESULT STDMETHODCALLTYPE GetStringValue(
        DWORD dwFieldID,
        PWSTR* ppwsz
    ) override;

    HRESULT STDMETHODCALLTYPE GetBitmapValue(
        DWORD dwFieldID,
        HBITMAP* phbmp
    ) override;

    HRESULT STDMETHODCALLTYPE GetCheckboxValue(
        DWORD dwFieldID,
        BOOL* pbChecked,
        PWSTR* ppwszLabel
    ) override;

    HRESULT STDMETHODCALLTYPE GetSubmitButtonValue(
        DWORD dwFieldID,
        DWORD* pdwAdjacentTo
    ) override;

    HRESULT STDMETHODCALLTYPE GetComboBoxValueCount(
        DWORD dwFieldID,
        DWORD* pcItems,
        DWORD* pdwSelectedItem
    ) override;

    HRESULT STDMETHODCALLTYPE GetComboBoxValueAt(
        DWORD dwFieldID,
        DWORD dwItem,
        PWSTR* ppwszItem
    ) override;

    HRESULT STDMETHODCALLTYPE SetStringValue(
        DWORD dwFieldID,
        PCWSTR pwz
    ) override;

    HRESULT STDMETHODCALLTYPE SetCheckboxValue(
        DWORD dwFieldID,
        BOOL bChecked
    ) override;

    HRESULT STDMETHODCALLTYPE SetComboBoxSelectedValue(
        DWORD dwFieldID,
        DWORD dwSelectedItem
    ) override;

    HRESULT STDMETHODCALLTYPE CommandLinkClicked(
        DWORD dwFieldID
    ) override;

    HRESULT STDMETHODCALLTYPE GetSerialization(
        CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
        CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon
    ) override;

    HRESULT STDMETHODCALLTYPE ReportResult(
        NTSTATUS ntsStatus,
        NTSTATUS ntsSubstatus,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon
    ) override;

private:
    ~PipaCredential();

    LONG _refCount;
};