const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, LevelFormat, BorderStyle } = require('docx');
const V = {seller_name: null, seller_inn: null, email: null, site: 'https://77-91-95-53.sslip.io:9443/miniapp/info',
  bot: '@WhiteHoleVPNbot', brand: 'WhiteHoleVPN', trial_days: '3', devices: '3', refund_days: '3'};
const TODO = {seller_name: '[ФИО]', seller_inn: '[ИНН]', email: '[e-mail]'};
function runs(text, base = {}) {
  const out = [];
  text.split(/(\*\*.+?\*\*)/).forEach(chunk => {
    if (!chunk) return;
    const bold = chunk.startsWith('**') && chunk.endsWith('**');
    const t = bold ? chunk.slice(2, -2) : chunk;
    t.split(/(\{\w+\})/).forEach(p => {
      if (!p) return;
      const m = /^\{(\w+)\}$/.exec(p);
      if (m && V[m[1]] === null) out.push(new TextRun({text: TODO[m[1]], bold: true, highlight: 'yellow', ...base}));
      else out.push(new TextRun({text: m ? V[m[1]] : p, bold: bold || base.bold, ...base}));
    });
  });
  return out;
}
function build(spec) {
  const kids = [
    new Paragraph({heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER, spacing: {after: 120}, children: [new TextRun({text: spec.title, bold: true})]}),
    new Paragraph({alignment: AlignmentType.CENTER, spacing: {after: 240}, children: [new TextRun({text: `Редакция от ${spec.date}`, color: '666666'})]}),
  ];
  for (const [kind, val] of spec.blocks) {
    if (kind === 'h') kids.push(new Paragraph({heading: HeadingLevel.HEADING_2, spacing: {before: 240, after: 100}, children: runs(val)}));
    else if (kind === 'ul') val.forEach(i => kids.push(new Paragraph({numbering: {reference: 'b', level: 0}, spacing: {after: 60}, children: runs(i)})));
    else if (kind === 'lead') kids.push(new Paragraph({spacing: {after: 200}, border: {left: {style: BorderStyle.SINGLE, size: 12, color: '999999', space: 8}}, children: runs(val, {italics: true})}));
    else kids.push(new Paragraph({spacing: {after: 100}, alignment: AlignmentType.JUSTIFIED, children: runs(val)}));
  }
  return new Document({
    styles: {default: {document: {run: {font: 'Arial', size: 22}}},
      paragraphStyles: [
        {id: 'Title', name: 'Title', basedOn: 'Normal', run: {size: 32, bold: true, font: 'Arial'}},
        {id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: {size: 24, bold: true, font: 'Arial'}, paragraph: {outlineLevel: 1}}]},
    numbering: {config: [{reference: 'b', levels: [{level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: {paragraph: {indent: {left: 720, hanging: 360}}}}]}]},
    sections: [{properties: {page: {margin: {top: 1134, bottom: 1134, left: 1134, right: 1134}}}, children: kids}],
  });
}
(async () => {
  for (const [name, file] of [['terms', 'Пользовательское соглашение WhiteHoleVPN.docx'], ['privacy', 'Политика конфиденциальности WhiteHoleVPN.docx']]) {
    const spec = JSON.parse(fs.readFileSync(`${name}.spec.json`, 'utf8'));
    fs.writeFileSync('/home/claude/' + file, await Packer.toBuffer(build(spec)));
    console.log('written', file);
  }
})();
