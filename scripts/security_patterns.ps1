Set-StrictMode -Version Latest

function Get-PipaHighConfidenceSecretPattern {
    <#
    Keep this expression compatible with both .NET regex and git grep -E.
    These are deliberately high-confidence token shapes; generic words such
    as "password" belong only to the working-tree policy below.
    #>
    return @(
        'BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY',
        'gh[oprsu]_[A-Za-z0-9]{20,}',
        'sk-(proj-)?[A-Za-z0-9_-]{20,}',
        'AKIA[0-9A-Z]{16}',
        'glpat-[A-Za-z0-9_-]{20,}',
        'xox[baprs]-[A-Za-z0-9-]{10,}',
        'npm_[A-Za-z0-9]{30,}',
        'AIza[0-9A-Za-z_-]{30,}',
        'mfa\.[A-Za-z0-9_-]{20,}',
        '(sk|rk)_live_[A-Za-z0-9]{16,}',
        '[0-9]{8,12}:[A-Za-z0-9_-]{35}'
    ) -join '|'
}

function Get-PipaWorkingTreeSecretPattern {
    return (Get-PipaHighConfidenceSecretPattern) +
        '|(?<![A-Za-z0-9_-])(password|secret|api[_-]?key|token)\s*[:=]\s*"'
}
