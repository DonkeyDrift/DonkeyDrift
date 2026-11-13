// tubnav namespace: zh values are the full Chinese translation; en values are
// the full English translation of every entry.
export const tubnav: { zh: Record<string, string>; en: Record<string, string> } = {
  zh: {
    // TubLibrary（原 TubNavigator 功能已合入 TubLibrary）
    'tub.steering': '转向',
    'tub.throttle': '油门',
    'tub.imageLoadError': '图像加载失败',
    'tub.first': '首条',
    'tub.firstRecordAria': '第一条记录',
    'tub.prevRecordAria': '上一条记录',
    'tub.nextRecordAria': '下一条记录',
    'tub.last': '末条',
    'tub.lastRecordAria': '最后一条记录',
    'tub.play': '播放',
    'tub.stop': '停止',
    'tub.startPlaybackAria': '开始播放',
    'tub.stopPlaybackAria': '停止播放',
    'tub.refreshAria': '刷新 Tub 记录',
    'tub.refreshTitle': '重新拉取当前 Tub 数据',
    // 数据缺失占位（TubLibrary 使用；模拟器配置相关旧键已删除）
    'tub.notAvailable': '无',
  },
  en: {
    // TubLibrary (features of the former TubNavigator merged into TubLibrary)
    'tub.steering': 'STEERING',
    'tub.throttle': 'Throttle',
    'tub.imageLoadError': 'Image Load Error',
    'tub.first': 'First',
    'tub.firstRecordAria': 'First record',
    'tub.prevRecordAria': 'Previous record',
    'tub.nextRecordAria': 'Next record',
    'tub.last': 'Last',
    'tub.lastRecordAria': 'Last record',
    'tub.play': 'Play',
    'tub.stop': 'Stop',
    'tub.startPlaybackAria': 'Start playback',
    'tub.stopPlaybackAria': 'Stop playback',
    'tub.refreshAria': 'Refresh tub records',
    'tub.refreshTitle': 'Reload current tub data from server',
    // Data-missing placeholder (used by TubLibrary; former simulator-config
    // keys were removed)
    'tub.notAvailable': 'N/A',
  },
};
