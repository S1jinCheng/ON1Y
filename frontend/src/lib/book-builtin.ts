import type { BookFormat, BookSource, BookSourcesFile } from "@/lib/book-types";

export const BOOK_ZLIB_BASE = "https://zh.z-lib.help";
export const BOOK_ANNAS_BASE = "https://tw.annas-archive.gl";
export const BOOK_FORMATS: BookFormat[] = ["epub", "pdf", "mobi"];

export function buildBuiltinSourcesSave(zlibEnabled: boolean, annasEnabled: boolean): BookSourcesFile {
  const sources: BookSource[] = [
    {
      id: "douban-fetch",
      name: "豆瓣",
      type: "fetch",
      parser: "douban_book",
      enabled: true,
      url_template: "https://search.douban.com/book/subject_search?search_text={query}",
      sort_order: 0
    },
    {
      id: "zlib-link",
      name: "Z-Library",
      type: "link",
      enabled: zlibEnabled,
      url_template: `${BOOK_ZLIB_BASE}/s/{query}`,
      sort_order: 1
    },
    {
      id: "annas-link",
      name: "安娜档案",
      type: "link",
      enabled: annasEnabled,
      url_template: `${BOOK_ANNAS_BASE}/search?q={query}`,
      sort_order: 2
    }
  ];
  return { version: 1, sources };
}

export function readBuiltinToggles(sourcesFile: BookSourcesFile): {
  zlibEnabled: boolean;
  annasEnabled: boolean;
} {
  const zlib = sourcesFile.sources.find((s) => s.id === "zlib-link");
  const annas = sourcesFile.sources.find((s) => s.id === "annas-link");
  return {
    zlibEnabled: zlib?.enabled ?? true,
    annasEnabled: annas?.enabled ?? true
  };
}
