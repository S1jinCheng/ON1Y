function wrapExportHtml(title: string, sections: Array<{ heading: string; html: string }>): string {
  const body = sections
    .filter((s) => s.html.trim())
    .map(
      (s) =>
        `<h2 style="font-size:16px;margin:18px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px;">${s.heading}</h2>${s.html}`
    )
    .join("");
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title></head><body style="font-family:Georgia,serif;line-height:1.6;padding:24px;max-width:720px;margin:0 auto;"><h1 style="font-size:22px;margin-bottom:8px;">${title}</h1>${body}</body></html>`;
}

export function downloadWordDocument(title: string, html: string): void {
  const blob = new Blob(["\ufeff", html], {
    type: "application/msword;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${sanitizeFilename(title)}.doc`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function printAsPdf(title: string, html: string): void {
  const frame = document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.border = "0";
  document.body.appendChild(frame);
  const doc = frame.contentDocument ?? frame.contentWindow?.document;
  if (!doc) {
    return;
  }
  doc.open();
  doc.write(html);
  doc.close();
  frame.contentWindow?.focus();
  frame.contentWindow?.print();
  setTimeout(() => frame.remove(), 1000);
}

export function exportItemDocument(options: {
  title: string;
  summaryHtml: string;
  originalHtml: string;
  notesHtml: string;
  format: "word" | "pdf";
  labels: { summary: string; original: string; notes: string };
}): void {
  const html = wrapExportHtml(options.title, [
    { heading: options.labels.summary, html: options.summaryHtml },
    { heading: options.labels.original, html: options.originalHtml },
    { heading: options.labels.notes, html: options.notesHtml }
  ]);
  if (options.format === "word") {
    downloadWordDocument(options.title, html);
  } else {
    printAsPdf(options.title, html);
  }
}

function sanitizeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80) || "export";
}
