'use strict';
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { panel, walk, details, FORMS } = require('./harness');

const emit = process.argv[2];
if (!emit) throw new Error('usage: localization.js <emit>');
const doc = lang => ({ document: { documentElement: { lang } } });
const zhCases = [doc('zh-CN'), doc('zh-Hans'), doc('zh_Hans_CN'), doc('zh-SG'), doc('schinese'),
  { navigator: { language: 'zh-CN' } }, { ...doc(''), navigator: { language: 'zh-CN' } }];
const itCases = [doc('it'), doc('it-IT'), doc('it_CH'), doc('italian'),
  { navigator: { language: 'it-IT' } }, { ...doc(''), navigator: { language: 'it' } }];
const twCases = [doc('zh-TW'), doc('zh-Hant'), doc('zh_Hant_TW'), doc('zh-HK'), doc('tchinese'),
  { navigator: { language: 'zh-TW' } }, { ...doc(''), navigator: { language: 'zh-Hant-TW' } }];
const enCases = [doc('en'), doc('fr'), doc('ita'), doc('iw'), doc('zh-Hantx'), {},
  { ...doc('en'), navigator: { language: 'zh-CN' } }, { ...doc('en'), navigator: { language: 'it-IT' } }];
// The same label in English, Simplified Chinese, Italian and Traditional Chinese; t() picks the one
// for the locale under test.
const lang = { en: 0, zh: 1, it: 2, tw: 3 };

for (const form of Object.keys(FORMS)) {
  for (const [language, cases] of [['zh', zhCases], ['tw', twCases], ['it', itCases], ['en', enCases]]) {
    const t = (...labels) => labels[lang[language]];
    for (const globals of cases) {
      const { render, written } = panel(emit, form, globals);
      const nodes = walk(render({ details: details('HADRON_GRAPHICS=dxmt %command%') }));
      const dropdowns = nodes.filter(n => n.type === 'Dropdown');
      assert.deepEqual(dropdowns[0].props.rgOptions.map(o => o.label), [
        t('DXMT (Metal)', 'DXMT（Metal）', 'DXMT (Metal)', 'DXMT（Metal）'),
        t('D3DMetal (CrossOver Wine)', 'D3DMetal（CrossOver Wine）', 'D3DMetal (CrossOver Wine)', 'D3DMetal（CrossOver Wine）'),
        'DXVK 3.1', 'DXVK 1.10',
        t("WineD3D (Wine's own)", 'WineD3D（Wine 自带）', 'WineD3D (integrato in Wine)', 'WineD3D（Wine 內建）')]);
      assert(nodes.some(n => n.type === 'Toggle' && n.props.label === t(
        'cnc-ddraw (old DirectDraw games)', 'cnc-ddraw（旧版 DirectDraw 游戏）', 'cnc-ddraw (vecchi giochi DirectDraw)',
        'cnc-ddraw（舊的 DirectDraw 遊戲）')));
      assert.equal(dropdowns[1].props.rgOptions[0].label, t('Off', '关闭', 'Disattivato', '關閉'));
      assert.deepEqual(dropdowns[0].props.rgOptions.map(o => o.data),
        ['dxmt', 'd3dmetal', 'dxvk', 'dxvk1', 'wined3d']);
      assert(nodes.some(n => n.props.label === t('Graphics', '图形', 'Grafica', '圖形')));
      assert(nodes.some(n => n.props.label === t(
        'Controllers', '控制器', 'Controller', '控制器')));
      const raw = nodes.find(n => n.props.label === t(
        'Let games read controllers directly (May break Steam Input. Not recommended)',
        '允许游戏直接读取控制器（可能导致 Steam Input 失效，不推荐）',
        'Lascia che i giochi leggano direttamente i controller (può interferire con Steam Input, sconsigliato)',
        '讓遊戲直接讀取控制器（可能讓 Steam Input 失效，不建議）'));
      const feats = panel(emit, form, globals, {
        ready: '{"HADRON_X":0}', feats: '[{k:"HADRON_X",l:"X",on:"1",off:"",dep:"",d:""}]' });
      const fnodes = walk(feats.render({ details: details('') }));
      assert(fnodes.some(n => n.props.label === t('Developer', '开发者', 'Developer', '開發者')));
      assert(fnodes.some(n => n.props.label === 'X' + t(' (not installed)', ' (未安装)', ' (not installed)', '（未安裝）')));
      raw.props.onChange(true);
      assert.equal(written.at(-1).opts, 'HADRON_RAW_CONTROLLERS=1 HADRON_GRAPHICS=dxmt %command%');
      const hud = nodes.find(n => n.props.label === t('Metal HUD', 'Metal 性能监视器', 'Metal HUD', 'Metal HUD'));
      hud.props.onChange(true);
      assert.equal(written.at(-1).opts, 'MTL_HUD_ENABLED=1 HADRON_GRAPHICS=dxmt %command%');
      for (const [mode, ...labels] of [
        ['compat-hint', 'Enable Squark under Properties > Compatibility to install and run the Windows version.',
          '请在“属性 > 兼容性”中启用 Squark，以安装并运行 Windows 版本。',
          'Abilita Squark in Proprietà > Compatibilità per installare e avviare la versione Windows.',
          '請在「內容 > 相容性」中啟用 Squark，以安裝並執行 Windows 版本。'],
        ['image-files-label', 'Image Files (*.tga,*.png,*.exe)', '图像文件 (*.tga,*.png,*.exe)',
          'File immagine (*.tga,*.png,*.exe)', '影像檔案 (*.tga,*.png,*.exe)'],
        ['library-windows-hint', 'Show only games that run on Windows and do not have a macOS version',
          'Show only games that run on Windows and do not have a macOS version',
          'Mostra solo i giochi che funzionano su Windows e non hanno una versione macOS',
          '只顯示能在 Windows 上執行、沒有 macOS 版本的遊戲'],
        ['library-windows-summary', 'Runs on Windows, no Mac OS version', 'Runs on Windows, no Mac OS version',
          'Funziona su Windows, nessuna versione macOS', '可在 Windows 上執行，沒有 macOS 版本'],
      ]) {
        const src = execFileSync(emit, [mode], { encoding: 'utf8' });
        assert.equal(new Function('globalThis', `return ${src}`)(globals), t(...labels));
      }
    }
  }
}
console.log('PASS: both panel shapes, Simplified/Traditional Chinese, Italian and English locales, fallback, labels and unchanged option values');
