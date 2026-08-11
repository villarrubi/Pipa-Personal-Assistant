#include <Windows.h>
#include <Unknwn.h>
#include <new>

#include "../include/PipaCredentialProvider.h"
#include "../include/PipaGuids.h"


LONG g_dllRefCount = 0;


class PipaClassFactory final : public IClassFactory
{
public:
    PipaClassFactory()
        : _refCount(1)
    {
        InterlockedIncrement(&g_dllRefCount);
    }

    ~PipaClassFactory()
    {
        InterlockedDecrement(&g_dllRefCount);
    }

    // IUnknown
    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** ppvObject
    ) override
    {
        if (ppvObject == nullptr)
        {
            return E_POINTER;
        }

        *ppvObject = nullptr;

        if (
            riid == IID_IUnknown ||
            riid == IID_IClassFactory
        )
        {
            *ppvObject = static_cast<IClassFactory*>(this);
            AddRef();

            return S_OK;
        }

        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override
    {
        return InterlockedIncrement(&_refCount);
    }

    ULONG STDMETHODCALLTYPE Release() override
    {
        LONG count = InterlockedDecrement(&_refCount);

        if (count == 0)
        {
            delete this;
            return 0;
        }

        return count;
    }

    // IClassFactory
    HRESULT STDMETHODCALLTYPE CreateInstance(
        IUnknown* pUnkOuter,
        REFIID riid,
        void** ppvObject
    ) override
    {
        if (ppvObject == nullptr)
        {
            return E_POINTER;
        }

        *ppvObject = nullptr;

        if (pUnkOuter != nullptr)
        {
            return CLASS_E_NOAGGREGATION;
        }

        PipaCredentialProvider* provider =
            new (std::nothrow) PipaCredentialProvider();

        if (provider == nullptr)
        {
            return E_OUTOFMEMORY;
        }

        HRESULT hr = provider->QueryInterface(
            riid,
            ppvObject
        );

        provider->Release();

        return hr;
    }

    HRESULT STDMETHODCALLTYPE LockServer(
        BOOL fLock
    ) override
    {
        if (fLock)
        {
            InterlockedIncrement(&g_dllRefCount);
        }
        else
        {
            InterlockedDecrement(&g_dllRefCount);
        }

        return S_OK;
    }

private:
    LONG _refCount;
};


// ---------------------------------------------------------
// COM DLL EXPORTS
// ---------------------------------------------------------

extern "C" STDAPI DllGetClassObject(
    REFCLSID rclsid,
    REFIID riid,
    LPVOID* ppvObject
)
{
    if (ppvObject == nullptr)
    {
        return E_POINTER;
    }

    *ppvObject = nullptr;

    if (rclsid != CLSID_PipaCredentialProvider)
    {
        return CLASS_E_CLASSNOTAVAILABLE;
    }

    PipaClassFactory* factory =
        new (std::nothrow) PipaClassFactory();

    if (factory == nullptr)
    {
        return E_OUTOFMEMORY;
    }

    HRESULT hr = factory->QueryInterface(
        riid,
        ppvObject
    );

    factory->Release();

    return hr;
}


extern "C" STDAPI DllCanUnloadNow()
{
    return g_dllRefCount == 0
        ? S_OK
        : S_FALSE;
}