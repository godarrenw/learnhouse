'use client'

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import en from '../locales/en.json';
import { loadDateLocale } from './format';
/* --- SYSU-SAM: 教学工具（ext）的文案 --- */
// 部署方自建功能的文案单独放 locales/ext/，不往上游的 en.json / zh.json 里插，
// 这样 rebase 上游时这两个大文件不会冲突。它们不是独立的 i18next namespace，
// 而是并进 `common` 的 `ext` 顶层 key —— 组件里照常 t('ext.xxx') 就能用。
// 只维护中英两份，其他语言由 fallbackLng: 'en' 兜底。
import extEn from '../locales/ext/en.json';
import extZh from '../locales/ext/zh.json';

const EXT_LOCALES: Record<string, any> = { en: extEn, zh: extZh };
/* --- /SYSU-SAM --- */

const LOCALE_LOADERS: Record<string, () => Promise<{ default: any }>> = {
  fr: () => import('../locales/fr.json'),
  de: () => import('../locales/de.json'),
  es: () => import('../locales/es.json'),
  ar: () => import('../locales/ar.json'),
  ja: () => import('../locales/ja.json'),
  pt: () => import('../locales/pt.json'),
  ru: () => import('../locales/ru.json'),
  zh: () => import('../locales/zh.json'),
  hi: () => import('../locales/hi.json'),
  ko: () => import('../locales/ko.json'),
  it: () => import('../locales/it.json'),
  tr: () => import('../locales/tr.json'),
  vi: () => import('../locales/vi.json'),
  id: () => import('../locales/id.json'),
  pl: () => import('../locales/pl.json'),
  uk: () => import('../locales/uk.json'),
  nl: () => import('../locales/nl.json'),
  th: () => import('../locales/th.json'),
  bn: () => import('../locales/bn.json'),
  fa: () => import('../locales/fa.json'),
  sk: () => import('../locales/sk.json'),
};

// Only bundle English; lazy-load all other locales on demand
const resources = {
  /* --- SYSU-SAM: 英文的 ext 文案直接进主包（en 本来就是打包进来的） --- */
  en: { common: { ...en, ext: extEn } },
  /* --- /SYSU-SAM --- */
};

async function loadLocale(lng: string) {
  const code = lng.split('-')[0]
  if (code === 'en' || !LOCALE_LOADERS[code]) return;
  if (i18n.hasResourceBundle(code, 'common')) return;

  try {
    const mod = await LOCALE_LOADERS[code]();
    i18n.addResourceBundle(code, 'common', mod.default, true, true);
    /* --- SYSU-SAM: 主语言包落地后再叠加 ext 文案 --- */
    // 必须在这之后。提前调 addResourceBundle 会让上面那行的
    // hasResourceBundle 判断变成 true，主语言包就永远不会加载了。
    if (EXT_LOCALES[code]) {
      i18n.addResourceBundle(code, 'common', { ext: EXT_LOCALES[code] }, true, true);
    }
    /* --- /SYSU-SAM --- */
  } catch (e) {
    console.warn(`Failed to load locale: ${lng}`, e);
  }
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'en',
    ns: ['common'],
    defaultNS: 'common',
    interpolation: {
      escapeValue: false, // react already safes from xss
    },
    detection: {
      order: ['localStorage', 'cookie', 'querystring', 'navigator', 'path', 'subdomain'],
      caches: ['localStorage', 'cookie'],
      lookupLocalStorage: 'i18nextLng',
      lookupCookie: 'i18next',
    },
    react: {
      useSuspense: false,
    }
  });

// Load the detected language if it's not English — export the promise
// so I18nProvider can wait for resources before rendering.
// The date locale rides along: dayjs keeps its own registry, and without this
// every "2 hours ago" renders in English no matter the language.
export const initialLocaleReady = Promise.all([
  loadLocale(i18n.language.split('-')[0]),
  loadDateLocale(i18n.language),
]).then(() => undefined);

/**
 * Switch language safely — preloads the bundle before switching
 * so the UI never flashes English as a fallback.
 */
export async function changeLanguage(lng: string) {
  await Promise.all([loadLocale(lng), loadDateLocale(lng)])
  return i18n.changeLanguage(lng)
}

export default i18n;
