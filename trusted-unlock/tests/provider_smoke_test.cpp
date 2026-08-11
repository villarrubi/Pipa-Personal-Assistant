#include <Windows.h>
#include <Unknwn.h>
#include <credentialprovider.h>

#include <filesystem>
#include <iostream>
#include <vector>

#include <initguid.h>
#include "../include/PipaGuids.h"
#include <io.h>
#include <fcntl.h>

using DllGetClassObjectFn = HRESULT (STDAPICALLTYPE*)(
    REFCLSID rclsid,
    REFIID riid,
    LPVOID* ppv
);

using DllCanUnloadNowFn = HRESULT (STDAPICALLTYPE*)();


int main()
{
    _setmode(_fileno(stdout), _O_U16TEXT);
    _setmode(_fileno(stderr), _O_U16TEXT);

    std::wcout << L"Pipα Trusted Unlock - Smoke Test\n";
    std::wcout << L"--------------------------------\n";

    std::vector<wchar_t> executablePathBuffer(32768, L'\0');
    DWORD executablePathLength = GetModuleFileNameW(
        nullptr,
        executablePathBuffer.data(),
        static_cast<DWORD>(executablePathBuffer.size())
    );

    if (executablePathLength == 0 || executablePathLength >= executablePathBuffer.size())
    {
        std::wcerr << L"[ERROR] No se pudo resolver la ruta del smoke test\n";
        return 1;
    }

    const std::filesystem::path dllPath =
        std::filesystem::path(executablePathBuffer.data()).parent_path() /
        L"PipaTrustedUnlock.dll";


    // 1. Cargar la DLL
    HMODULE module = LoadLibraryExW(
        dllPath.c_str(),
        nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32
    );

    if (module == nullptr)
    {
        std::wcerr
            << L"[ERROR] No se pudo cargar PipaTrustedUnlock.dll\n";

        return 1;
    }

    std::wcout << L"[OK] DLL cargada\n";


    // 2. Buscar exports COM
    auto dllGetClassObject =
        reinterpret_cast<DllGetClassObjectFn>(
            GetProcAddress(
                module,
                "DllGetClassObject"
            )
        );

    auto dllCanUnloadNow =
        reinterpret_cast<DllCanUnloadNowFn>(
            GetProcAddress(
                module,
                "DllCanUnloadNow"
            )
        );

    if (dllGetClassObject == nullptr)
    {
        std::wcerr
            << L"[ERROR] No existe DllGetClassObject\n";

        FreeLibrary(module);
        return 1;
    }

    if (dllCanUnloadNow == nullptr)
    {
        std::wcerr
            << L"[ERROR] No existe DllCanUnloadNow\n";

        FreeLibrary(module);
        return 1;
    }

    std::wcout << L"[OK] Exports COM encontrados\n";


    // 3. Crear la Class Factory
    IClassFactory* factory = nullptr;

    HRESULT hr = dllGetClassObject(
        CLSID_PipaCredentialProvider,
        IID_IClassFactory,
        reinterpret_cast<void**>(&factory)
    );

    if (FAILED(hr) || factory == nullptr)
    {
        std::wcerr
            << L"[ERROR] DllGetClassObject fallo. HRESULT: 0x"
            << std::hex
            << hr
            << L"\n";

        FreeLibrary(module);
        return 1;
    }

    std::wcout << L"[OK] IClassFactory creada\n";


    // 4. Crear ICredentialProvider
    ICredentialProvider* provider = nullptr;

    hr = factory->CreateInstance(
        nullptr,
        IID_ICredentialProvider,
        reinterpret_cast<void**>(&provider)
    );

    factory->Release();
    factory = nullptr;

    if (FAILED(hr) || provider == nullptr)
    {
        std::wcerr
            << L"[ERROR] No se pudo crear ICredentialProvider. HRESULT: 0x"
            << std::hex
            << hr
            << L"\n";

        FreeLibrary(module);
        return 1;
    }

    std::wcout << L"[OK] ICredentialProvider creado\n";


    // 5. Probar escenario de login
    hr = provider->SetUsageScenario(
        CPUS_LOGON,
        0
    );

    if (FAILED(hr))
    {
        std::wcerr
            << L"[ERROR] SetUsageScenario fallo. HRESULT: 0x"
            << std::hex
            << hr
            << L"\n";

        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout << L"[OK] CPUS_LOGON aceptado\n";


    // 6. Consultar numero de campos
    DWORD fieldCount = 999;

    hr = provider->GetFieldDescriptorCount(
        &fieldCount
    );

    if (FAILED(hr))
    {
        std::wcerr
            << L"[ERROR] GetFieldDescriptorCount fallo\n";

        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] Numero de campos: "
        << fieldCount
        << L"\n";

    if (fieldCount != 2)
    {
        std::wcerr << L"[ERROR] Se esperaban exactamente 2 campos\n";
        provider->Release();
        FreeLibrary(module);
        return 1;
    }

    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* invalidDescriptor = nullptr;
    if (provider->GetFieldDescriptorAt(fieldCount, &invalidDescriptor) != E_INVALIDARG ||
        invalidDescriptor != nullptr)
    {
        std::wcerr << L"[ERROR] Se acepto un descriptor fuera de rango\n";
        provider->Release();
        FreeLibrary(module);
        return 1;
    }

    for (DWORD fieldIndex = 0; fieldIndex < fieldCount; ++fieldIndex)
    {
        CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* descriptor = nullptr;

        hr = provider->GetFieldDescriptorAt(
            fieldIndex,
            &descriptor
        );

        if (FAILED(hr) || descriptor == nullptr)
        {
            std::wcerr << L"[ERROR] No se pudo obtener el descriptor de campo\n";
            provider->Release();
            FreeLibrary(module);
            return 1;
        }

        if (descriptor->dwFieldID != fieldIndex || descriptor->pszLabel == nullptr)
        {
            std::wcerr << L"[ERROR] Descriptor de campo inconsistente\n";
            CoTaskMemFree(descriptor->pszLabel);
            CoTaskMemFree(descriptor);
            provider->Release();
            FreeLibrary(module);
            return 1;
        }

        CoTaskMemFree(descriptor->pszLabel);
        CoTaskMemFree(descriptor);
    }

    std::wcout << L"[OK] Descriptores de campos validos\n";


    // 7. Consultar numero de credenciales
    DWORD credentialCount = 999;
    DWORD defaultCredential = 999;
    BOOL autoLogon = TRUE;

    hr = provider->GetCredentialCount(
        &credentialCount,
        &defaultCredential,
        &autoLogon
    );

    if (FAILED(hr))
    {
        std::wcerr
            << L"[ERROR] GetCredentialCount fallo\n";

        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] Numero de credenciales: "
        << credentialCount
        << L"\n";

    std::wcout
        << L"[OK] AutoLogon: "
        << (autoLogon ? L"TRUE" : L"FALSE")
        << L"\n";

    if (credentialCount != 1 || defaultCredential != 0 || autoLogon != FALSE)
    {
        std::wcerr << L"[ERROR] Conteo/default/autologon inseguros\n";
        provider->Release();
        FreeLibrary(module);
        return 1;
    }


    // 8. Obtener la credencial 0
    ICredentialProviderCredential* credential = nullptr;

    hr = provider->GetCredentialAt(
        0,
        &credential
    );

    if (FAILED(hr) || credential == nullptr)
    {
        std::wcerr
            << L"[ERROR] No se pudo obtener la credencial 0. HRESULT: 0x"
            << std::hex
            << hr
            << L"\n";

        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout << L"[OK] Credencial Pipα obtenida\n";


    // 9. Leer titulo
    PWSTR title = nullptr;

    hr = credential->GetStringValue(
        0,
        &title
    );

    if (FAILED(hr) || title == nullptr)
    {
        std::wcerr
            << L"[ERROR] No se pudo leer el titulo\n";

        credential->Release();
        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] Titulo: "
        << title
        << L"\n";

    CoTaskMemFree(title);
    title = nullptr;


    // 10. Leer estado
    PWSTR status = nullptr;

    hr = credential->GetStringValue(
        1,
        &status
    );

    if (FAILED(hr) || status == nullptr)
    {
        std::wcerr
            << L"[ERROR] No se pudo leer el estado\n";

        credential->Release();
        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] Estado: "
        << status
        << L"\n";

    CoTaskMemFree(status);
    status = nullptr;


    // 11. Comprobar SetSelected
    BOOL credentialAutoLogon = TRUE;

    hr = credential->SetSelected(
        &credentialAutoLogon
    );

    if (FAILED(hr))
    {
        std::wcerr
            << L"[ERROR] SetSelected fallo\n";

        credential->Release();
        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] Credential AutoLogon: "
        << (credentialAutoLogon ? L"TRUE" : L"FALSE")
        << L"\n";

    if (credentialAutoLogon != FALSE)
    {
        std::wcerr << L"[ERROR] SetSelected intento habilitar autologon\n";
        credential->Release();
        provider->Release();
        FreeLibrary(module);
        return 1;
    }


    // 12. Comprobar GetSerialization
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE serializationResponse =
        CPGSR_NO_CREDENTIAL_NOT_FINISHED;

    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION serialization = {};

    PWSTR optionalStatusText = nullptr;

    CREDENTIAL_PROVIDER_STATUS_ICON statusIcon = CPSI_NONE;

    hr = credential->GetSerialization(
        &serializationResponse,
        &serialization,
        &optionalStatusText,
        &statusIcon
    );

    if (FAILED(hr))
    {
        std::wcerr
            << L"[ERROR] GetSerialization fallo. HRESULT: 0x"
            << std::hex
            << hr
            << L"\n";

        credential->Release();
        provider->Release();
        FreeLibrary(module);

        return 1;
    }

    std::wcout
        << L"[OK] GetSerialization ejecutado\n";

    std::wcout
        << L"[OK] Pipα todavia NO entrega credenciales a Windows\n";

    if (
        serializationResponse != CPGSR_NO_CREDENTIAL_NOT_FINISHED ||
        serialization.ulAuthenticationPackage != 0 ||
        serialization.clsidCredentialProvider != GUID_NULL ||
        serialization.rgbSerialization != nullptr ||
        serialization.cbSerialization != 0
    )
    {
        std::wcerr
            << L"[ERROR] La serializacion no esta vacia o no esta marcada como no finalizada\n";

        if (serialization.rgbSerialization != nullptr)
        {
            CoTaskMemFree(serialization.rgbSerialization);
        }

        credential->Release();
        provider->Release();
        FreeLibrary(module);
        return 1;
    }

    if (optionalStatusText != nullptr)
    {
        CoTaskMemFree(optionalStatusText);
        optionalStatusText = nullptr;
    }


    // 13. Liberar credencial
    credential->Release();
    credential = nullptr;


    // 14. Liberar provider
    provider->Release();
    provider = nullptr;


    // 15. Comprobar si la DLL puede descargarse
    hr = dllCanUnloadNow();

    if (hr == S_OK)
    {
        std::wcout
            << L"[OK] DllCanUnloadNow devuelve S_OK\n";
    }
    else
    {
        std::wcout
            << L"[WARN] DllCanUnloadNow devuelve S_FALSE\n";
    }


    // 16. Descargar DLL
    FreeLibrary(module);


    std::wcout << L"\n";
    std::wcout << L"================================\n";
    std::wcout << L"SMOKE TEST COMPLETADO\n";
    std::wcout << L"================================\n";

    return 0;
}
