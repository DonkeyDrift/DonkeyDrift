// common namespace: zh values mirror the current UI strings verbatim (the
// "Chinese interface" is exactly today's mixed zh/en UI); en values are the
// full English translation of every entry.
export const common: { zh: Record<string, string>; en: Record<string, string> } = {
  zh: {
    // Layout top navigation
    'common.nav.tubManager': 'Tub Manager',
    'common.nav.trainer': 'Trainer',
    'common.nav.drive': 'Drive',
    'common.nav.pilotArena': 'Pilot Arena',
    'common.nav.carConnector': 'Car Connector',
    'common.nav.menu': '菜单',
    // App shell
    'common.app.somethingWentWrong': 'Something went wrong.',
    'common.app.failedToRefreshTub': 'Failed to refresh tub',
    'common.app.errorPrefix': 'Error: {message}',
    'common.loading': 'Loading',
    // ConfigLoader
    'common.configLoader.failedToLoad': 'Failed to load config',
    'common.configLoader.failedToLoadFromDir': 'Failed to load config from selected directory',
    'common.configLoader.title': 'Config Loader',
    'common.configLoader.description': 'Select car directory (created via donkey createcar)',
    'common.configLoader.apiLabel': 'API: {origin}/api',
    'common.configLoader.pathPlaceholder': 'Config path, e.g. /home/dkc/projects/mycar',
    'common.configLoader.pathInputAria': 'Config path input field',
    'common.configLoader.browse': 'Browse',
    'common.configLoader.browseAria': 'Browse configuration directory',
    'common.configLoader.load': 'Load',
    'common.configLoader.loadAria': 'Load configuration',
    'common.configLoader.configLoaded': 'Config loaded: {path}',
    'common.configLoader.noConfig': 'No config loaded',
    'common.configLoader.selectCarDirectory': 'Select Car Directory',
    // FileBrowserModal
    'common.fileBrowser.selectDirectory': 'Select Directory',
    'common.fileBrowser.failedToLoad': 'Failed to load directories',
    'common.fileBrowser.loading': 'Loading...',
    'common.fileBrowser.goBack': 'Go Back',
    'common.fileBrowser.noDirectories': 'No directories found',
    'common.fileBrowser.cancel': 'Cancel',
    'common.fileBrowser.selectCurrent': 'Select Current Directory',
    // SidePanel
    'common.sidePanel.loaders': 'Loaders',
    'common.sidePanel.connectors': 'Connectors',
    // GitHubLink
    'common.githubLink.label': 'DonkeyDrift on GitHub',
    // EnterButtons
    'common.enterButtons.kimiCodeWeb': '打开 Kimi Code Web',
    'common.enterButtons.kimiCodeWebTitle': '启动 kimi 并在新标签页打开 Kimi Code Web',
    'common.enterButtons.kimiCodeWebStarting': '启动中…',
    'common.enterButtons.kimiCodeWebFailed': '打开 Kimi Code Web 失败：{message}',
    'common.enterButtons.kimiCodeWebNetworkError': '网络错误或请求超时（kimi 冷启动较慢，可稍后重试）',
    'common.enterButtons.drifterConsole': '打开 DrifterConsole',
    'common.enterButtons.drifterConsoleTitle': '打开 ESP32 Drifter Console',
    'common.enterButtons.scanning': '扫描中…',
    'common.enterButtons.consoleNotFound': '未在局域网中发现 Drifter Console 设备',
    // services/api.ts
    'common.unknownError': '未知错误',
    'common.cannotConnectBackend': '无法连接后端服务，请确认已执行 donkey web 并且后端端口可访问',
    'common.close': '关闭',
  },
  en: {
    // Layout top navigation
    'common.nav.tubManager': 'Tub Manager',
    'common.nav.trainer': 'Trainer',
    'common.nav.drive': 'Drive',
    'common.nav.pilotArena': 'Pilot Arena',
    'common.nav.carConnector': 'Car Connector',
    'common.nav.menu': 'Menu',
    // App shell
    'common.app.somethingWentWrong': 'Something went wrong.',
    'common.app.failedToRefreshTub': 'Failed to refresh tub',
    'common.app.errorPrefix': 'Error: {message}',
    'common.loading': 'Loading',
    // ConfigLoader
    'common.configLoader.failedToLoad': 'Failed to load config',
    'common.configLoader.failedToLoadFromDir': 'Failed to load config from selected directory',
    'common.configLoader.title': 'Config Loader',
    'common.configLoader.description': 'Select car directory (created via donkey createcar)',
    'common.configLoader.apiLabel': 'API: {origin}/api',
    'common.configLoader.pathPlaceholder': 'Config path, e.g. /home/dkc/projects/mycar',
    'common.configLoader.pathInputAria': 'Config path input field',
    'common.configLoader.browse': 'Browse',
    'common.configLoader.browseAria': 'Browse configuration directory',
    'common.configLoader.load': 'Load',
    'common.configLoader.loadAria': 'Load configuration',
    'common.configLoader.configLoaded': 'Config loaded: {path}',
    'common.configLoader.noConfig': 'No config loaded',
    'common.configLoader.selectCarDirectory': 'Select Car Directory',
    // FileBrowserModal
    'common.fileBrowser.selectDirectory': 'Select Directory',
    'common.fileBrowser.failedToLoad': 'Failed to load directories',
    'common.fileBrowser.loading': 'Loading...',
    'common.fileBrowser.goBack': 'Go Back',
    'common.fileBrowser.noDirectories': 'No directories found',
    'common.fileBrowser.cancel': 'Cancel',
    'common.fileBrowser.selectCurrent': 'Select Current Directory',
    // SidePanel
    'common.sidePanel.loaders': 'Loaders',
    'common.sidePanel.connectors': 'Connectors',
    // GitHubLink
    'common.githubLink.label': 'DonkeyDrift on GitHub',
    // EnterButtons
    'common.enterButtons.kimiCodeWeb': 'Open Kimi Code Web',
    'common.enterButtons.kimiCodeWebTitle': 'Start kimi and open Kimi Code Web in a new tab',
    'common.enterButtons.kimiCodeWebStarting': 'Starting…',
    'common.enterButtons.kimiCodeWebFailed': 'Failed to open Kimi Code Web: {message}',
    'common.enterButtons.kimiCodeWebNetworkError': 'Network error or request timed out (kimi starts slowly, please retry)',
    'common.enterButtons.drifterConsole': 'Open DrifterConsole',
    'common.enterButtons.drifterConsoleTitle': 'Open ESP32 Drifter Console',
    'common.enterButtons.scanning': 'Scanning…',
    'common.enterButtons.consoleNotFound': 'No Drifter Console device found on the LAN',
    // services/api.ts
    'common.unknownError': 'Unknown error',
    'common.cannotConnectBackend': 'Cannot connect to the backend service. Please make sure donkey web is running and the backend port is accessible.',
    'common.close': 'Close',
  },
};
