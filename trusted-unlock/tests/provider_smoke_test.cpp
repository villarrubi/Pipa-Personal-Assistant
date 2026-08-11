#include <Windows.h>
#include <Unknwn.h>
#include <credentialprovider.h>

#include <iostream>

#include <initguid.h>
#include "../include/PipaGuids.h"


using DllGetClassObjectFn = HRESULT (STDAPICALLTYPE*)(
    REFCLSID rclsid,
    REFIID riid,
    LPVOID* ppv
);

using DllCanUnloadNowFn = HRESULT (STDAPICALLTYPE*)();


int main()
{
    std::wcout << L"Pipα Trusted Unlock - Smoke Test\n";
    std::wcout << L"--------------------------------\n";

    const wchar_t* dllPath =
        L"Release\\PipaTrustedUnlock.dll";

    // 1. Cargar la DLL
    HMODULE module = LoadLibraryW(dllPath);

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
            GetProcAddress(module, "DllGetClassObject")
        );

    auto dllCanUnloadNow =
        reinterpret_cast<DllCanUnloadNowFn>(
            GetProcAddress(module, "DllCanUnloadNow")
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


    // 3. Pedir la Class Factory
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


    // 4. Crear nuestro ICredentialProvider
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


    // 6. Consultar campos
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


    // 7. Consultar credenciales
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


    // 8. Liberar provider
    provider->Release();
    provider = nullptr;


    // 9. Preguntar si la DLL puede descargarse
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


    FreeLibrary(module);

    std::wcout << L"\n";
    std::wcout << L"================================\n";
    std::wcout << L"SMOKE TEST COMPLETADO\n";
    std::wcout << L"================================\n";

    return 0;
}