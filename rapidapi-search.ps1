<#
.SYNOPSIS
  Поиск API/провайдеров на RapidAPI Hub без UI — вытаскивает JSON, а не парсит HTML.

.HOW IT WORKS
  Страница поиска RapidAPI — это Next.js SSR. В HTML вшит тег
  <script id="__NEXT_DATA__" type="application/json">...</script>,
  внутри которого лежат ВСЕ результаты поиска в структурированном виде.
  Мы забираем этот блок и парсим как JSON — верстка при этом не важна.

.SETUP
  1. Открой rapidapi.com в браузере, залогинься.
  2. DevTools (F12) -> вкладка Network -> обнови страницу -> клик по первому
     document-запросу -> Copy -> Copy as cURL (или скопируй заголовок Cookie).
  3. Положи cookie в переменную окружения (обновляй когда cf_clearance/jwt_auth протухнут):
       $env:RAPIDAPI_COOKIE = "__cflb=...; cf_clearance=...; jwt_auth=...; connect.sid=..."

.EXAMPLE
  .\rapidapi-search.ps1 -Term youtube
  .\rapidapi-search.ps1 -Term youtube -Category Data -SortBy ByRelevance -Raw
#>
param(
    [Parameter(Mandatory = $true)][string]$Term,
    [string]$Category = "Data",              # Data, Video, Sports, Finance, ...
    [ValidateSet("ByRelevance","ByPopularity","ByLatest")][string]$SortBy = "ByRelevance",
    [switch]$Raw,                            # сохранить сырой __NEXT_DATA__ в файл
    [string]$RawOut = ".\rapidapi-nextdata.json"
)

$cookie = $env:RAPIDAPI_COOKIE
if (-not $cookie) {
    throw "Сначала задай `$env:RAPIDAPI_COOKIE (см. блок .SETUP в шапке скрипта)."
}

$term = [uri]::EscapeDataString($Term)
$url  = "https://rapidapi.com/search/$Category?term=$term&sortBy=$SortBy"

$headers = @{
    "accept"          = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    "accept-language" = "en-US,en;q=0.9"
    "referer"         = "https://rapidapi.com/"
    "user-agent"      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
    "cookie"          = $cookie
}

Write-Host "GET $url" -ForegroundColor DarkGray
$resp = Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing

# --- вытащить блок __NEXT_DATA__ ---
$m = [regex]::Match(
    $resp.Content,
    '<script id="__NEXT_DATA__" type="application/json">(?<json>.*?)</script>',
    [System.Text.RegularExpressions.RegexOptions]::Singleline
)
if (-not $m.Success) {
    throw "Не нашёл __NEXT_DATA__. Скорее всего Cloudflare/логин отдал заглушку — обнови cf_clearance и jwt_auth в cookie."
}

$data = $m.Groups["json"].Value | ConvertFrom-Json

if ($Raw) {
    ($data | ConvertTo-Json -Depth 40) | Out-File -FilePath $RawOut -Encoding utf8
    Write-Host "Сырой JSON сохранён: $RawOut" -ForegroundColor DarkGray
}

# --- рекурсивно найти объекты-API внутри произвольной структуры props ---
# Признак карточки API: есть name/title И slug|route, часто вложенный provider/user.
function Find-ApiObjects {
    param($node, [System.Collections.ArrayList]$acc)
    if ($null -eq $node) { return }

    if ($node -is [System.Collections.IEnumerable] -and $node -isnot [string]) {
        foreach ($item in $node) { Find-ApiObjects -node $item -acc $acc }
        return
    }

    if ($node.PSObject -and $node.PSObject.Properties) {
        $props = $node.PSObject.Properties.Name
        $hasName  = ($props -contains "name") -or ($props -contains "title")
        $hasRoute = ($props -contains "slug") -or ($props -contains "route") -or ($props -contains "apiSlug")
        if ($hasName -and $hasRoute) { [void]$acc.Add($node) }

        foreach ($p in $node.PSObject.Properties) {
            Find-ApiObjects -node $p.Value -acc $acc
        }
    }
}

$found = New-Object System.Collections.ArrayList
Find-ApiObjects -node $data.props -acc $found

if ($found.Count -eq 0) {
    Write-Warning "Карточки API не распознаны автоматически. Запусти с -Raw и посмотри структуру в $RawOut (ищи props.pageProps)."
    return
}

$found | ForEach-Object {
    $slug     = $_.slug     ?? $_.route ?? $_.apiSlug
    $provider = $_.provider ?? $_.user  ?? $_.owner
    $providerName = if ($provider) { $provider.name ?? $provider.username ?? $provider.slug } else { $null }
    [pscustomobject]@{
        Name     = $_.name ?? $_.title
        Provider = $providerName
        Slug     = $slug
        Url      = if ($slug) { "https://rapidapi.com/$providerName/api/$slug" } else { $null }
    }
} | Sort-Object Name -Unique | Format-Table -AutoSize
