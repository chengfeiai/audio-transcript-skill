/*!
 * minutes-tools.js — 录音纪要阅读器通用能力：导出 Word / 复制文字
 * ---------------------------------------------------------------
 * 设计约束：
 *   1. 零依赖、零网络请求，file:// 下可直接用（很多人是双击打开、不联网）。
 *   2. .docx 在浏览器内手工打包（store 模式 zip + 最小 OOXML），不是把 HTML
 *      改后缀冒充 Word —— 那种文件 WPS / Word 会提示格式不符。
 *   3. 复制取的是 DOM 语义，不是 innerText —— 时间锚点补 [mm:ss]、列表补符号、
 *      卡片补标题，粘到聊天工具 / 文档里仍然成立。
 *   4. 样式自注入，接入方只需在 body 末尾加一个 script 标签，不必改 CSS/HTML。
 *
 * 用法：把本文件内容原样放进一个 script 标签，位置在页面自身脚本之后。
 * 注意：本文件会被内联进 HTML，源码里绝不能出现字符串形式的结束标签，
 *       否则 HTML 解析器会提前截断整段脚本（2026-10-30 踩过这个坑）。
 */
(function (root) {
  'use strict';

  var api = {};

  /* ============================================================
   * 一、区块抽取：DOM -> 线性块
   * 块类型 title/sub/h1/h2/h3/kv/li/p/quote/small/seg
   * 块字段 { t, parts, n?, time?, who? }
   * parts 是 [{t:'文本', b:加粗, i:斜体}]，保留原文重点。
   * ============================================================ */

  function squash(s) {
    return String(s).replace(/[ \t\u00a0]+/g, ' ');
  }

  /* 把元素内联内容拆成带样式的片段；时间锚点补成 [mm:ss] */
  function richParts(el) {
    var parts = [];
    if (!el) return parts;

    (function walk(node, bold, italic) {
      for (var c = node.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3) {
          var t = squash(c.nodeValue);
          if (t) parts.push({ t: t, b: bold, i: italic });
          continue;
        }
        if (c.nodeType !== 1) continue;
        var tag = c.tagName.toLowerCase();
        if (tag === 'br') { parts.push({ t: '\n' }); continue; }
        if (tag === 'input' || tag === 'svg') continue;
        if (c.classList && (c.classList.contains('mt-menu') || c.classList.contains('mt-card-btn') ||
            c.classList.contains('mt-seg-btn') || c.classList.contains('cp-btn') ||
            c.classList.contains('star') || c.classList.contains('mascot'))) continue;
        if (tag === 'a' && c.classList.contains('cite')) {
          parts.push({ t: '[' + (c.getAttribute('data-t') || '') + ']' });
          continue;
        }
        walk(c, bold || tag === 'b' || tag === 'strong', italic || tag === 'i' || tag === 'em');
      }
    })(el, false, false);

    /* 合并同样式的相邻片段，减少 run 数量 */
    var out = [];
    parts.forEach(function (p) {
      if (!p.t) return;
      var last = out[out.length - 1];
      if (last && !last.b === !p.b && !last.i === !p.i) last.t += p.t;
      else out.push({ t: p.t, b: p.b, i: p.i });
    });
    /* 去掉首尾空白 */
    if (out.length) {
      out[0].t = out[0].t.replace(/^[ \t\n]+/, '');
      var e = out[out.length - 1];
      e.t = e.t.replace(/[ \t\n]+$/, '');
      out = out.filter(function (p) { return p.t !== ''; });
    }
    return out;
  }

  function textOf(parts, keepBr) {
    var s = parts.map(function (p) { return p.t; }).join('');
    s = keepBr ? s.replace(/[ \t\u00a0]*\n[ \t\u00a0]*/g, '\n')
               : s.replace(/\s+/g, ' ');
    return s.replace(/^\s+|\s+$/g, '');
  }

  function colorOf(who) {
    return { '干部方': '1E64FF', '当事人': '9A6218', '第三人': '2C6E49' }[who] || '4A5566';
  }

  /* 通用兜底：不依赖具体模板的类名，只认语义标签 */
  function genericBlocks(scope) {
    var out = [];
    var sel = 'h1,h2,h3,h4,.doc-title,.block-title,.gc-title,.t-row,li,p,blockquote';
    Array.prototype.forEach.call(scope.querySelectorAll(sel), function (el) {
      if (el.closest('.banner') || el.closest('footer') || el.closest('summary')) return;
      var cls = el.classList;

      if (cls.contains('t-row')) {
        var ts = el.querySelector('.t-ts'), tx = el.querySelector('.t-txt');
        if (!tx) return;
        var t = ts ? textOf(richParts(ts)).replace(/[\[\]]/g, '') : '';
        var m = textOf(richParts(tx)).match(/^说话人\s*(\d+)\s*[:：]/);
        out.push({ t: 'seg', parts: richParts(tx), time: t, who: m ? '说话人' + m[1] : '' });
        return;
      }
      if (cls.contains('block-title')) { out.push({ t: 'h1', parts: richParts(el) }); return; }
      if (cls.contains('gc-title')) { out.push({ t: 'h2', parts: richParts(el) }); return; }
      if (cls.contains('doc-title')) { out.push({ t: 'title', parts: richParts(el) }); return; }

      var tag = el.tagName;
      if (tag === 'LI') { out.push({ t: 'li', parts: richParts(el) }); return; }
      if (tag === 'P' || tag === 'BLOCKQUOTE') {
        if (el.closest('li')) return;
        out.push({ t: 'p', parts: richParts(el) });
        return;
      }
      if (tag === 'H1') { out.push({ t: 'title', parts: richParts(el) }); return; }
      if (tag === 'H2') { out.push({ t: 'h1', parts: richParts(el) }); return; }
      out.push({ t: 'h2', parts: richParts(el) });
    });
    return out;
  }

  /* 主入口：把一个容器（左栏 .doc 或右栏 #transcript）读成块数组 */
  function collectDom(scope) {
    var blocks = [];
    if (!scope) return blocks;

    function add(t, el, extra) {
      var parts = typeof el === 'string' ? [{ t: el }] : richParts(el);
      if (!textOf(parts)) return;
      var b = { t: t, parts: parts };
      if (extra) for (var k in extra) b[k] = extra[k];
      blocks.push(b);
    }

    /* ---------- 卡片 ---------- */
    function card(el) {
      var h = el.querySelector('.card-hd h4') || el.querySelector('.card-hd');
      if (h) add('h2', h);
      var bd = el.querySelector('.card-bd');
      if (bd) {
        var lis = bd.querySelectorAll('li');
        if (lis.length) Array.prototype.forEach.call(lis, function (li) { add('li', li); });
        else {
          var ps = bd.querySelectorAll('p');
          if (ps.length) Array.prototype.forEach.call(ps, function (p) { add('p', p); });
          else add('p', bd);
        }
      }
      var cm = el.querySelector('.card-cm');
      if (cm) add('quote', cm);
    }

    /* ---------- 对照面板 ---------- */
    function duel(el) {
      var h = el.querySelector('.duel-hd > span');
      if (h) add('h2', h);
      var legend = el.querySelector('.duel-legend');
      if (legend) add('small', legend);
      Array.prototype.forEach.call(el.querySelectorAll('.duel-side'), function (side) {
        var role = side.querySelector('.duel-role');
        if (role) add('kv', role);
        Array.prototype.forEach.call(side.querySelectorAll('.verdict'), function (v) {
          var s = v.querySelector('span'), b = v.querySelector('b');
          var parts = [];
          if (s) parts = parts.concat(richParts(s));
          if (b) parts = parts.concat([{ t: '：' }], richParts(b));
          if (textOf(parts)) blocks.push({ t: 'li', parts: parts });
        });
        var note = side.querySelector('.duel-note');
        if (note) add('quote', note);
      });
    }

    /* ---------- 处理链条节点 ---------- */
    function step(el) {
      var top = el.querySelector('.step-top');
      var parts = [];
      if (top) {
        var k = top.querySelector('b');
        if (k) parts = parts.concat(richParts(k));
        var tm = top.querySelector('.step-time');
        if (tm) parts.push({ t: '　' + textOf(richParts(tm)) });
        var tags = top.querySelectorAll('.tag');
        var tagTxt = Array.prototype.map.call(tags, function (x) { return textOf(richParts(x)); }).filter(Boolean);
        if (tagTxt.length) parts.push({ t: '　（' + tagTxt.join(' / ') + '）' });
      }
      if (textOf(parts)) blocks.push({ t: 'h2', parts: parts });
      Array.prototype.forEach.call(el.querySelectorAll('.step-bd p'), function (p) {
        if (p.classList.contains('card-cm')) return;
        add('p', p);
      });
      var cm = el.querySelector('.card-cm');
      if (cm) add('quote', cm);
    }

    /* ---------- 待核实清单 ---------- */
    function checks(el) {
      Array.prototype.forEach.call(el.querySelectorAll('li'), function (li) {
        var ck = li.querySelector('.ck') || li;
        var b = ck.querySelector('b'), em = ck.querySelector('em');
        var parts = [{ t: '□ ' }];
        if (b) parts = parts.concat(richParts(b));
        if (em) parts = parts.concat([{ t: '　' }], richParts(em));
        if (!b && !em) parts = parts.concat(richParts(ck));
        if (textOf(parts)) blocks.push({ t: 'li', parts: parts });
      });
    }

    /* ---------- 章节 ---------- */
    function section(sec) {
      var hd = sec.querySelector('.sec-hd');
      if (hd) {
        var no = hd.querySelector('.sec-no'), h = hd.querySelector('h3');
        var parts = [];
        if (no) parts.push({ t: textOf(richParts(no)) + '　' });
        if (h) parts = parts.concat(richParts(h));
        var sub = hd.querySelector('.sec-sub');
        if (textOf(parts)) blocks.push({ t: 'h1', parts: parts });
        if (sub) add('small', sub);
      }
      Array.prototype.forEach.call(sec.querySelectorAll('.card'), card);
      Array.prototype.forEach.call(sec.querySelectorAll('.duel'), duel);
      Array.prototype.forEach.call(sec.querySelectorAll('.step'), step);
      Array.prototype.forEach.call(sec.querySelectorAll('.checks'), checks);
    }

    /* ---------- 对话段 ---------- */
    function segs(host) {
      Array.prototype.forEach.call(host.querySelectorAll('.seg'), function (s) {
        var who = s.getAttribute('data-who') || '';
        var t = s.getAttribute('data-t') || '';
        var x = s.querySelector('.seg-x');
        var parts = richParts(x);
        if (!textOf(parts)) return;
        blocks.push({ t: 'seg', parts: parts, time: t, who: who });
      });
    }

    if (scope.id === 'transcript') {                 /* 右栏单列全文 */
      segs(scope);
      return blocks;
    }

    /* 不认识的模板：按语义标签线性抽取，保证别的版式也能导出 */
    if (!scope.querySelector('.doc') && !(scope.classList && scope.classList.contains('doc'))) {
      return genericBlocks(scope);
    }

    /* 头部在 .doc 里，各章节与声明是 .doc 的兄弟节点 —— 两者都要看 */
    var docPart = scope.querySelector ? scope.querySelector('.doc') : null;
    if (!docPart && scope.classList && scope.classList.contains('doc')) docPart = scope;
    var host = docPart || scope;

    var kicker = host.querySelector('.kicker');
    if (kicker) add('small', kicker);

    var h1 = host.querySelector('h1');
    if (h1) add('title', h1);

    var sub = host.querySelector('.doc-sub');
    if (sub) add('sub', sub);

    Array.prototype.forEach.call(host.querySelectorAll('.meta > div'), function (m) {
      var dt = m.querySelector('dt'), dd = m.querySelector('dd');
      if (!dt || !dd) return;
      var parts = richParts(dt).concat([{ t: '：' }], richParts(dd));
      blocks.push({ t: 'kv', parts: parts });
    });

    var brief = host.querySelector('.brief');
    if (brief) {
      var bh = brief.querySelector('h2');
      if (bh) add('h1', bh);
      Array.prototype.forEach.call(brief.querySelectorAll('ol > li'), function (li, i) {
        var b = { t: 'li', parts: richParts(li), n: i + 1 };
        if (textOf(b.parts)) blocks.push(b);
      });
      var chips = brief.querySelectorAll('.chip');
      if (chips.length) {
        var parts = [{ t: '标签：' }];
        Array.prototype.forEach.call(chips, function (c, i) {
          var tag = c.querySelector('i');
          if (i) parts.push({ t: '　·　' });
          if (tag) parts = parts.concat(richParts(tag), [{ t: ' ' }]);
          var rest = c.cloneNode(true);
          var ri = rest.querySelector('i');
          if (ri) ri.parentNode.removeChild(ri);
          parts = parts.concat(richParts(rest));
        });
        if (textOf(parts)) blocks.push({ t: 'p', parts: parts });
      }
    }

    Array.prototype.forEach.call(scope.querySelectorAll('section.sec'), section);

    var decl = scope.querySelector('.decl');
    if (decl) {
      var ps = decl.querySelectorAll('p');
      if (ps.length) {
        blocks.push({ t: 'h1', parts: [{ t: '声明' }] });
        Array.prototype.forEach.call(ps, function (p) {
          add(p.classList.contains('stamp') ? 'small' : 'p', p);
        });
      }
    }

    return blocks;
  }

  /* ============================================================
   * 二、Markdown（剪贴板用）
   * ============================================================ */

  function mdInline(parts) {
    return parts.map(function (p) {
      var t = p.t.replace(/\n+/g, ' ');
      return p.b ? '**' + t + '**' : t;
    }).join('').replace(/[ \t]{2,}/g, ' ');
  }

  function toMarkdown(blocks) {
    var out = [];
    blocks.forEach(function (b) {
      var inl = mdInline(b.parts);
      switch (b.t) {
        case 'title': out.push('# ' + inl); break;
        case 'sub':   out.push('*' + inl + '*'); break;
        case 'h1':    out.push('\n## ' + inl); break;
        case 'h2':    out.push('\n### ' + inl); break;
        case 'h3':    out.push('#### ' + inl); break;
        case 'kv':    out.push('- ' + inl); break;
        case 'li':    out.push((b.n ? b.n + '. ' : '- ') + inl); break;
        case 'quote': out.push('> ' + inl); break;
        case 'small': out.push(inl); break;
        case 'seg':   out.push('[' + b.time + '] ' + b.who + '：' + inl); break;
        default:      out.push(inl);
      }
    });
    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }

  /* ============================================================
   * 三、DOCX：blocks -> OOXML -> zip（store）
   * ============================================================ */

  function xmlEsc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function para(style, content, pPrExtra) {
    var parts = typeof content === 'string' ? [{ t: content }] : content;
    var runs = '';
    parts.forEach(function (p) {
      String(p.t).split('\n').forEach(function (line, i) {
        if (i) runs += '<w:r><w:br/></w:r>';
        if (!line) return;
        var rpr = '';
        if (p.b) rpr += '<w:b/><w:bCs/>';
        if (p.i) rpr += '<w:i/><w:iCs/>';
        if (p.c) rpr += '<w:color w:val="' + p.c + '"/>';
        if (p.sz) rpr += '<w:sz w:val="' + p.sz + '"/><w:szCs w:val="' + p.sz + '"/>';
        rpr = rpr ? '<w:rPr>' + rpr + '</w:rPr>' : '';
        runs += '<w:r>' + rpr + '<w:t xml:space="preserve">' + xmlEsc(line) + '</w:t></w:r>';
      });
    });
    return '<w:p><w:pPr><w:pStyle w:val="' + style + '"/>' + (pPrExtra || '') +
           '</w:pPr>' + runs + '</w:p>';
  }

  var STYLE_MAP = {
    title: 'TitleX', sub: 'SubX', h1: 'H1X', h2: 'H2X', h3: 'H3X',
    kv: 'KVX', li: 'LIX', p: 'PX', quote: 'QX', small: 'SX'
  };

  function blocksToBody(blocks) {
    return blocks.map(function (b) {
      if (b.t === 'seg') {
        return para('SEGX', [
          { t: b.time + '  ', c: '8A94A3', sz: 18 },
          { t: b.who + '：', c: colorOf(b.who), b: true, sz: 19 },
          { t: textOf(b.parts, true) }
        ]);
      }
      var style = STYLE_MAP[b.t] || 'PX';
      var content = b.parts.slice();
      if (b.t === 'li' && b.n) content = [{ t: b.n + '. ', b: false }].concat(content);
      else if (b.t === 'li') content = [{ t: '· ' }].concat(content);
      return para(style, content);
    }).join('');
  }

  function documentXml(bodyXml) {
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      '<w:body>' + bodyXml +
      '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>' +
      '<w:pgMar w:top="1304" w:right="1247" w:bottom="1304" w:left="1247" w:header="851" w:footer="992" w:gutter="0"/>' +
      '<w:cols w:space="425"/><w:docGrid w:linePitch="312"/></w:sectPr>' +
      '</w:body></w:document>';
  }

  var STYLES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    '<w:docDefaults><w:rPrDefault><w:rPr>' +
      '<w:rFonts w:ascii="Helvetica Neue" w:hAnsi="Helvetica Neue" w:cs="Arial"/>' +
      '<w:lang w:val="en-US" w:eastAsia="zh-CN"/>' +
      '<w:color w:val="22272E"/><w:sz w:val="21"/><w:szCs w:val="21"/>' +
    '</w:rPr></w:rPrDefault>' +
    '<w:pPrDefault><w:pPr><w:spacing w:line="306" w:lineRule="auto" w:after="80"/></w:pPr></w:pPrDefault>' +
    '</w:docDefaults>' +
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' +
    /* 主标题 */
    '<w:style w:type="paragraph" w:styleId="TitleX"><w:name w:val="Minutes Title"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:spacing w:before="0" w:after="140" w:line="288" w:lineRule="auto"/><w:outlineLvl w:val="0"/></w:pPr>' +
      '<w:rPr><w:b/><w:color w:val="161C26"/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>' +
    /* 副标题 */
    '<w:style w:type="paragraph" w:styleId="SubX"><w:name w:val="Minutes Sub"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:spacing w:after="220"/></w:pPr>' +
      '<w:rPr><w:i/><w:color w:val="5A6472"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>' +
    /* 节标题 */
    '<w:style w:type="paragraph" w:styleId="H1X"><w:name w:val="Minutes Section"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="5" w:color="D6DDE8"/></w:pBdr>' +
        '<w:spacing w:before="360" w:after="140" w:line="288" w:lineRule="auto"/>' +
        '<w:outlineLvl w:val="0"/></w:pPr>' +
      '<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/><w:color w:val="1B4FCC"/></w:rPr></w:style>' +
    /* 卡片标题 */
    '<w:style w:type="paragraph" w:styleId="H2X"><w:name w:val="Minutes Card"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>' +
      '<w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/><w:color w:val="1A2233"/></w:rPr></w:style>' +
    '<w:style w:type="paragraph" w:styleId="H3X"><w:name w:val="Minutes Sub Head"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:keepNext/><w:spacing w:before="180" w:after="60"/></w:pPr>' +
      '<w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/><w:color w:val="3A4353"/></w:rPr></w:style>' +
    /* 键值 */
    '<w:style w:type="paragraph" w:styleId="KVX"><w:name w:val="Minutes KV"/><w:basedOn w:val="Normal"/>' +
      '<w:pPr><w:spacing w:after="40"/></w:pPr>' +
      '<w:rPr><w:color w:val="3A4353"/></w:rPr></w:style>' +
    /* 列表 */
    '<w:style w:type="paragraph" w:styleId="LIX"><w:name w:val="Minutes List"/><w:basedOn w:val="Normal"/>' +
      '<w:pPr><w:spacing w:after="80"/><w:ind w:left="284" w:hanging="284"/></w:pPr>' +
      '<w:rPr><w:color w:val="2B3442"/></w:rPr></w:style>' +
    /* 正文 */
    '<w:style w:type="paragraph" w:styleId="PX"><w:name w:val="Minutes Para"/><w:basedOn w:val="Normal"/>' +
      '<w:rPr><w:color w:val="2B3442"/></w:rPr></w:style>' +
    /* 点评 */
    '<w:style w:type="paragraph" w:styleId="QX"><w:name w:val="Minutes Quote"/><w:basedOn w:val="Normal"/>' +
      '<w:pPr><w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="C9D4E4"/></w:pBdr>' +
        '<w:spacing w:before="80" w:after="140"/><w:ind w:left="284"/></w:pPr>' +
      '<w:rPr><w:color w:val="5E6875"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>' +
    /* 小字 */
    '<w:style w:type="paragraph" w:styleId="SX"><w:name w:val="Minutes Small"/><w:basedOn w:val="Normal"/>' +
      '<w:rPr><w:color w:val="77828F"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>' +
    /* 对话段 */
    '<w:style w:type="paragraph" w:styleId="SEGX"><w:name w:val="Minutes Seg"/><w:basedOn w:val="Normal"/>' +
      '<w:pPr><w:spacing w:after="60" w:line="316" w:lineRule="auto"/></w:pPr>' +
      '<w:rPr><w:color w:val="2B3442"/></w:rPr></w:style>' +
    '</w:styles>';

  /* ---- zip（store，无压缩） ---- */
  var CRC_TABLE = null;
  function crc32(u8) {
    if (!CRC_TABLE) {
      CRC_TABLE = new Int32Array(256);
      for (var n = 0; n < 256; n++) {
        var c = n;
        for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        CRC_TABLE[n] = c;
      }
    }
    var crc = -1;
    for (var i = 0; i < u8.length; i++) crc = (crc >>> 8) ^ CRC_TABLE[(crc ^ u8[i]) & 0xFF];
    return (crc ^ -1) >>> 0;
  }

  function zipStore(files, when) {
    var enc = new TextEncoder();
    var chunks = [], central = [], offset = 0;
    var d = when || new Date();
    var dosTime = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    var dosDate = (((d.getFullYear() - 1980) & 0x7F) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();

    files.forEach(function (f) {
      var data = typeof f.data === 'string' ? enc.encode(f.data) : f.data;
      var name = enc.encode(f.name);
      var crc = crc32(data);
      var start = offset;

      var lh = new Uint8Array(30 + name.length);
      var lv = new DataView(lh.buffer);
      lv.setUint32(0, 0x04034b50, true);
      lv.setUint16(4, 20, true);
      lv.setUint16(6, 0x0800, true);          /* UTF-8 文件名 */
      lv.setUint16(8, 0, true);               /* store */
      lv.setUint16(10, dosTime, true);
      lv.setUint16(12, dosDate, true);
      lv.setUint32(14, crc, true);
      lv.setUint32(18, data.length, true);
      lv.setUint32(22, data.length, true);
      lv.setUint16(26, name.length, true);
      lv.setUint16(28, 0, true);
      lh.set(name, 30);
      chunks.push(lh, data);

      var cd = new Uint8Array(46 + name.length);
      var cv = new DataView(cd.buffer);
      cv.setUint32(0, 0x02014b50, true);
      cv.setUint16(4, 20, true);
      cv.setUint16(6, 20, true);
      cv.setUint16(8, 0x0800, true);
      cv.setUint16(10, 0, true);
      cv.setUint16(12, dosTime, true);
      cv.setUint16(14, dosDate, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, data.length, true);
      cv.setUint32(24, data.length, true);
      cv.setUint16(28, name.length, true);
      cv.setUint16(30, 0, true);
      cv.setUint16(32, 0, true);
      cv.setUint16(34, 0, true);
      cv.setUint16(36, 0, true);
      cv.setUint32(38, 0, true);
      cv.setUint32(42, start, true);
      cd.set(name, 46);
      central.push(cd);

      offset += lh.length + data.length;
    });

    var cdSize = central.reduce(function (n, c) { return n + c.length; }, 0);
    var eocd = new Uint8Array(22);
    var ev = new DataView(eocd.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(4, 0, true);
    ev.setUint16(6, 0, true);
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, cdSize, true);
    ev.setUint32(16, offset, true);
    ev.setUint16(20, 0, true);

    var all = chunks.concat(central, [eocd]);
    var total = all.reduce(function (n, c) { return n + c.length; }, 0);
    var out = new Uint8Array(total);
    var pos = 0;
    all.forEach(function (c) { out.set(c, pos); pos += c.length; });
    return out;
  }

  function docxBlob(blocks, meta) {
    meta = meta || {};
    var body = blocksToBody(blocks);
    var title = meta.title || '录音纪要';
    var core = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ' +
      'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ' +
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
      '<dc:title>' + xmlEsc(title) + '</dc:title>' +
      '<dc:creator>录音转写</dc:creator>' +
      '<cp:lastModifiedBy>录音转写</cp:lastModifiedBy>' +
      '<dcterms:created xsi:type="dcterms:W3CDTF">' + new Date().toISOString().replace(/\.\d+Z$/, 'Z') + '</dcterms:created>' +
      '</cp:coreProperties>';

    var files = [
      { name: '[Content_Types].xml', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
        '</Types>' },
      { name: '_rels/.rels', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
        '</Relationships>' },
      { name: 'word/_rels/document.xml.rels', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        '</Relationships>' },
      { name: 'word/document.xml', data: documentXml(body) },
      { name: 'word/styles.xml', data: STYLES },
      { name: 'docProps/core.xml', data: core }
    ];

    var bytes = zipStore(files);
    return { bytes: bytes, blob: new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }) };
  }

  /* ============================================================
   * 四、剪贴板
   * ============================================================ */

  function copyText(text) {
    return new Promise(function (resolve, reject) {
      var fallback = function () {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0';
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error('execCommand failed'));
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(resolve, fallback);
      } else fallback();
    });
  }

  /* ============================================================
   * 五、导出 API（node 下也可直接调用，便于校验 docx 结构）
   * ============================================================ */

  api.collectDom = collectDom;
  api.toMarkdown = toMarkdown;
  api.docxBlob = docxBlob;
  api.zipStore = zipStore;
  api.copyText = copyText;
  api.crc32 = crc32;

  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof root !== 'undefined') root.MinutesTools = api;

  /* node 环境到此为止，以下只服务浏览器 */
  if (typeof document === 'undefined') return;

  /* ============================================================
   * 六、UI 装配
   * ============================================================ */

  var CSS = [
    /* 按钮本体 */
    '.mt-btn{display:inline-flex;align-items:center;justify-content:center;gap:4px;',
    '  height:28px;min-width:28px;padding:0 8px;border:0;border-radius:8px;background:transparent;',
    '  color:#5A6472;font:500 12px/1 "PingFang SC","Microsoft YaHei",sans-serif;',
    '  cursor:pointer;transition:background .15s,color .15s;white-space:nowrap}',
    '.mt-btn:hover{background:rgba(30,100,255,.09);color:#1E64FF}',
    '.mt-btn svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.7;',
    '  stroke-linecap:round;stroke-linejoin:round;flex:none}',
    '.mt-btn[disabled]{opacity:.55;cursor:default}',
    '.mt-caret{width:9px;height:9px;stroke-width:2.2}',
    /* 下拉 */
    '.mt-wrap{position:relative;display:inline-flex}',
    /* 页面没提供工具栏时的兜底 */
    '.mt-float{position:fixed;top:14px;right:14px;z-index:150;display:flex;align-items:center;gap:2px;',
    '  padding:4px;background:#fff;border:1px solid rgba(20,30,50,.12);border-radius:14px;',
    '  box-shadow:0 8px 24px -6px rgba(20,30,50,.22)}',
    '.mt-menu{position:absolute;top:calc(100% + 8px);right:0;min-width:196px;z-index:120;',
    '  background:#fff;border:1px solid rgba(20,30,50,.12);border-radius:12px;padding:6px;',
    '  box-shadow:0 14px 36px -8px rgba(20,30,50,.24),0 2px 6px rgba(20,30,50,.06)}',
    '.mt-menu[hidden]{display:none}',
    '.mt-menu button{display:block;width:100%;text-align:left;border:0;background:transparent;',
    '  border-radius:8px;padding:8px 10px;cursor:pointer;',
    '  font:600 12.5px/1.45 "PingFang SC","Microsoft YaHei",sans-serif;color:#26303D}',
    '.mt-menu button:hover{background:#EFF5FF;color:#1E64FF}',
    '.mt-menu small{display:block;margin-top:2px;font:400 11px/1.4 "PingFang SC";color:#8A94A3}',
    /* 卡片/段落上的单条复制 */
    '.mt-seg-btn{position:absolute;right:3px;top:50%;transform:translateY(-50%);',
    '  width:22px;height:22px;padding:0;border-radius:6px;opacity:0;pointer-events:none;',
    '  background:rgba(255,255,255,.96);border:1px solid rgba(20,30,50,.10);',
    '  box-shadow:0 1px 4px rgba(20,30,50,.10);z-index:3}',
    '.seg:hover .mt-seg-btn,.t-row:hover .mt-seg-btn,.mt-seg-btn:focus-visible{opacity:1;pointer-events:auto}',
    '.mt-seg-btn svg{width:13px;height:13px}',
    '.seg,.t-row{position:relative}',
    '.mt-card-btn{position:absolute;top:9px;right:10px;height:22px;padding:0 7px;',
    '  border-radius:6px;opacity:0;pointer-events:none;font-size:11px;',
    '  background:rgba(255,255,255,.97);border:1px solid rgba(20,30,50,.10);',
    '  box-shadow:0 1px 4px rgba(20,30,50,.10);z-index:3}',
    '.card:hover .mt-card-btn,.step:hover .mt-card-btn,.brief:hover .mt-card-btn,',
    '.mt-card-btn:focus-visible{opacity:1;pointer-events:auto}',
    '@media (hover:none){.mt-seg-btn,.mt-card-btn{opacity:1;pointer-events:auto}}',
    /* 提示条复用页面 #toast；没有时兜底一个 */
    '.mt-toast{position:fixed;left:50%;bottom:78px;transform:translate(-50%,12px);z-index:200;',
    '  background:rgba(22,30,44,.94);color:#fff;padding:9px 16px;border-radius:10px;',
    '  font:500 12.5px/1.4 "PingFang SC";opacity:0;pointer-events:none;transition:.22s;}',
    '.mt-toast.on{opacity:1;transform:translate(-50%,0)}',
    '@media print{.mt-btn,.mt-seg-btn,.mt-card-btn,.mt-menu,.mt-toast,.mt-float{display:none!important}',
    '  .seg,.t-row{padding-right:9px!important}}'
  ].join('\n');

  function injectCss() {
    if (document.getElementById('mt-style')) return;
    var s = document.createElement('style');
    s.id = 'mt-style';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  var ICON = {
    word: '<svg viewBox="0 0 24 24"><path d="M14 3v5h5"/><path d="M19 8v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7z"/><path d="m9 12 1.4 5 1.6-3.4L13.6 17 15 12"/></svg>',
    copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
    caret: '<svg class="mt-caret" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>'
  };

  var toastTimer = null;
  function toast(msg) {
    var el = document.getElementById('toast');
    if (el) {
      el.textContent = msg;
      el.classList.add('on');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { el.classList.remove('on'); }, 2600);
      return;
    }
    el = document.querySelector('.mt-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'mt-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('on'); }, 2600);
  }

  function mkBtn(html, title, cls) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'mt-btn' + (cls ? ' ' + cls : '');
    b.title = title || '';
    b.setAttribute('aria-label', title || '');
    b.innerHTML = html;
    return b;
  }

  /* 纪要正文的宿主：兼容新双栏版、旧深色版与未知模板 */
  function docScope() {
    return document.getElementById('colL') ||
           document.querySelector('.doc') ||
           document.querySelector('.wrap') ||
           document.body;
  }

  function docTitle() {
    var h1 = document.querySelector('.doc h1');
    var t = '';
    if (h1) t = h1.innerHTML.split(/<br\s*\/?>/i)[0].replace(/<[^>]+>/g, '').replace(/\s+/g, '');
    if (!t) t = (document.title || '录音纪要').split('·')[0].trim();
    return t.replace(/[\\/:*?"<>|]/g, '').slice(0, 40) || '录音纪要';
  }

  function stamp() {
    var d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate());
  }

  function saveBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(url);
      if (a.parentNode) a.parentNode.removeChild(a);
    }, 5000);
  }

  function exportDocx(withTranscript) {
    var blocks = collectDom(docScope());
    if (withTranscript) {
      var tr = document.getElementById('transcript') ||
               document.querySelector('.t-body') ||
               document.querySelector('.transcript-block');
      if (tr) {
        var segs = collectDom(tr);
        if (segs.length) {
          blocks.push({ t: 'h1', parts: [{ t: '转写全文（' + segs.length + ' 段）' }] });
          blocks.push({ t: 'small', parts: [{ t: '以下为逐段转写，时间戳对应原始录音；点不开链接时请回听原音核对。' }] });
          blocks = blocks.concat(segs);
        }
      }
    }
    var title = docTitle();
    var res = docxBlob(blocks, { title: title });
    saveBlob(res.blob, title + '-纪要' + (withTranscript ? '含全文' : '') + '-' + stamp() + '.docx');
  }

  function init() {
    if (document.querySelector('.mt-wrap')) return;
    injectCss();

    /* ---- 左栏：导出 Word + 复制纪要 ---- */
    var pillL = document.querySelector('#pL .pill') || document.querySelector('.p-hd .pill');
    if (!pillL) {
      /* 别的模板没有工具栏：挂一个浮动工具条，能力照常可用 */
      pillL = document.createElement('div');
      pillL.className = 'mt-float';
      document.body.appendChild(pillL);
    }
    if (pillL) {
      var wrap = document.createElement('span');
      wrap.className = 'mt-wrap';
      var btnWord = mkBtn(ICON.word + 'Word' + ICON.caret, '导出为 Word 文档（.docx）');
      var menu = document.createElement('div');
      menu.className = 'mt-menu';
      menu.hidden = true;

      var segCount = document.querySelectorAll('#transcript .seg').length;
      var options = [
        { txt: '纪要 + 全文', tip: segCount ? '含 ' + segCount + ' 段转写原文，适合归档' : '含转写原文', full: true },
        { txt: '仅纪要', tip: '只要结论、争议、链条与清单', full: false }
      ];
      options.forEach(function (o, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.innerHTML = (i === 0 ? '★ ' : '') + o.txt + '<small>' + o.tip + '</small>';
        b.addEventListener('click', function () {
          menu.hidden = true;
          btnWord.disabled = true;
          try {
            exportDocx(o.full);
            toast('已导出 Word：' + (o.full ? '纪要 + 全文' : '仅纪要'));
          } catch (err) {
            toast('导出失败：' + (err && err.message ? err.message : '未知错误'));
          }
          setTimeout(function () { btnWord.disabled = false; }, 600);
        });
        menu.appendChild(b);
      });

      btnWord.addEventListener('click', function (e) {
        e.stopPropagation();
        menu.hidden = !menu.hidden;
      });
      document.addEventListener('click', function () { menu.hidden = true; });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') menu.hidden = true; });

      wrap.appendChild(btnWord);
      wrap.appendChild(menu);
      pillL.insertBefore(wrap, pillL.firstChild);

      var btnCopyDoc = mkBtn(ICON.copy, '复制纪要全文（Markdown，可直接粘贴）');
      btnCopyDoc.addEventListener('click', function () {
        var md = toMarkdown(collectDom(docScope()));
        copyText(md).then(function () { toast('纪要全文已复制（' + md.length + ' 字）'); },
                           function () { toast('复制被浏览器拦截，请手动选中文字'); });
      });
      pillL.insertBefore(btnCopyDoc, wrap.nextSibling);
    }

    /* ---- 右栏：复制全文 ---- */
    var hasTranscript = !!(document.getElementById('transcript') || document.querySelector('.t-row'));
    var pillR = document.querySelector('#pR .pill') || (hasTranscript ? pillL : null);
    if (pillR) {
      var btnCopyTr = mkBtn(ICON.copy, '复制转写全文（每行带时间戳与说话人）');
      btnCopyTr.addEventListener('click', function () {
        var trEl = document.getElementById('transcript') ||
                   document.querySelector('.t-body') ||
                   document.querySelector('.transcript-block');
        var segs = collectDom(trEl);
        var txt = segs.map(function (s) {
          return '[' + s.time + '] ' + s.who + '：' + textOf(s.parts);
        }).join('\n');
        copyText(txt).then(function () { toast('转写全文已复制（' + segs.length + ' 段 · ' + txt.length + ' 字）'); },
                           function () { toast('复制被浏览器拦截，请手动选中文字'); });
      });
      pillR.insertBefore(btnCopyTr, pillR.firstChild);
    }

    /* ---- 卡片 / 节点 / 结论：hover 复制单条 ---- */
    function addCardBtn(el, label) {
      if (el.querySelector('.mt-card-btn')) return;
      if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
      var b = mkBtn(ICON.copy + '<span>复制</span>', '复制这条' + (label || ''), 'mt-card-btn');
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var text = toMarkdown(singleBlocks(el)).trim();
        copyText(text).then(function () { toast('已复制这条' + (label || '')); },
                           function () { toast('复制被浏览器拦截'); });
      });
      el.appendChild(b);
    }

    /* 单条抽取：把元素临时当作根，复用 collectDom 的分支 */
    function singleBlocks(el) {
      var cls = el.classList;
      var blocks = [];
      if (cls.contains('card') || cls.contains('step')) {
        var doc = document.createElement('div');
        doc.className = 'doc';
        var sec = document.createElement('section');
        sec.className = 'sec';
        var box = document.createElement('div');
        box.className = cls.contains('card') ? 'grid' : 'steps';
        box.appendChild(el.cloneNode(true));
        sec.appendChild(box);
        doc.appendChild(sec);
        return collectDom(doc);
      }
      if (cls.contains('brief')) {
        var w3 = document.createElement('div');
        w3.className = 'doc';
        w3.appendChild(el.cloneNode(true));
        return collectDom(w3);
      }
      blocks.push({ t: 'p', parts: richParts(el) });
      return blocks;
    }

    Array.prototype.forEach.call(document.querySelectorAll('.card'), function (el) { addCardBtn(el, '卡片'); });
    Array.prototype.forEach.call(document.querySelectorAll('.step'), function (el) { addCardBtn(el, '节点'); });
    Array.prototype.forEach.call(document.querySelectorAll('.brief'), function (el) { addCardBtn(el, '结论'); });

    /* ---- 对话段：hover 复制 ---- */
    Array.prototype.forEach.call(document.querySelectorAll('#transcript .seg, .t-row'), function (s) {
      if (s.querySelector('.mt-seg-btn')) return;
      var b = mkBtn(ICON.copy, '复制这一段', 'mt-seg-btn');
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var who = s.getAttribute('data-who') || '';
        var t = s.getAttribute('data-t') || '';
        var ts = s.querySelector('.t-ts');
        if (!t && ts) t = ts.textContent.replace(/[\[\]\s]/g, '');
        var x = s.querySelector('.seg-x') || s.querySelector('.t-txt');
        var body = x ? x.textContent.replace(/\s+/g, ' ').trim() : '';
        var txt = (t ? '[' + t + '] ' : '') + (who ? who + '：' : '') + body;
        copyText(txt).then(function () { toast('已复制' + (t ? ' ' + t + ' 段' : '这一段')); },
                           function () { toast('复制被浏览器拦截'); });
      });
      s.appendChild(b);
      s.style.paddingRight = '30px';
    });

    /* ---- 快捷键：⌘/Ctrl + Shift + C 复制纪要全文 ---- */
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'c' || e.key === 'C')) {
        var col = docScope();
        if (!col) return;
        e.preventDefault();
        copyText(toMarkdown(collectDom(col))).then(function () { toast('纪要全文已复制'); }, function () {});
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})(typeof window !== 'undefined' ? window : globalThis);
