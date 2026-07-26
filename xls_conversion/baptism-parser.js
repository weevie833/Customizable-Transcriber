(function () {
  const HEADERS = [
    "Record #",
    "Image #",
    "Year",
    "Date",
    "Child",
    "Child's Father",
    "Child's Mother",
    "Godparent 1",
    "Godparent 1's Father",
    "Godparent 2",
    "Godparent 2's Father",
  ];

  const MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  const ORDINALS = {
    first: 1,
    second: 2,
    third: 3,
    fourth: 4,
    fifth: 5,
    sixth: 6,
    seventh: 7,
    eighth: 8,
    ninth: 9,
    tenth: 10,
    eleventh: 11,
    twelfth: 12,
    thirteenth: 13,
    fourteenth: 14,
    fifteenth: 15,
    sixteenth: 16,
    seventeenth: 17,
    eighteenth: 18,
    nineteenth: 19,
    twentieth: 20,
    "twenty first": 21,
    "twenty-first": 21,
    "twenty second": 22,
    "twenty-second": 22,
    "twenty third": 23,
    "twenty-third": 23,
    "twenty fourth": 24,
    "twenty-fourth": 24,
    "twenty fifth": 25,
    "twenty-fifth": 25,
    "twenty sixth": 26,
    "twenty-sixth": 26,
    "twenty seventh": 27,
    "twenty-seventh": 27,
    "twenty eighth": 28,
    "twenty-eighth": 28,
    "twenty ninth": 29,
    "twenty-ninth": 29,
    thirtieth: 30,
    "thirty first": 31,
    "thirty-first": 31,
  };

  const NUMBER_WORDS = {
    zero: 0,
    one: 1,
    two: 2,
    three: 3,
    four: 4,
    five: 5,
    six: 6,
    seven: 7,
    eight: 8,
    nine: 9,
    ten: 10,
    eleven: 11,
    twelve: 12,
    thirteen: 13,
    fourteen: 14,
    fifteen: 15,
    sixteen: 16,
    seventeen: 17,
    eighteen: 18,
    nineteen: 19,
    twenty: 20,
    thirty: 30,
    forty: 40,
    fifty: 50,
    sixty: 60,
    seventy: 70,
    eighty: 80,
    ninety: 90,
  };

  const SURNAME_PREFIXES = new Set([
    "da",
    "dal",
    "de",
    "del",
    "della",
    "di",
    "la",
    "le",
    "li",
    "lo",
  ]);

  function convertTextToPsv(sourceText, options = {}) {
    return convertText(sourceText, options).psv;
  }

  function convertText(sourceText, options = {}) {
    const imageCheck = verifyImageSequence(sourceText, options.imageRange || "", options.imageOverrides || "");
    const entries = splitEntries(sourceText, options);
    const parsedEntries = entries
      .map((entry) => ({ entry, english: getEntryEnglish(entry) }))
      .filter((item) => item.english)
      .map((item) => ({ ...item, row: parseEntry(item.entry) }))
      .filter((item) => item.row);
    const rows = parsedEntries.map((item) => item.row);
    const expectedImages = parseImageRange(options.imageRange || "");
    const foundImages = new Set(rows.map((row) => row["Image #"]).filter(Boolean));
    const missingImages = expectedImages.filter((imageNumber) => !foundImages.has(imageNumber));
    const exceptionLog = buildExceptionLog(sourceText, options, imageCheck, parsedEntries);
    const psv = [HEADERS.join("|"), ...rows.map((row) => HEADERS.map((header) => escapePsv(row[header])).join("|"))].join("\n");

    return { psv, rows, missingImages, foundImages: [...foundImages], imageCheck, exceptionLog };
  }

  function verifyImageSequence(sourceText, imageRange = "", imageOverrides = "") {
    const normalized = sourceText.replace(/\r\n?/g, "\n");
    const expectedImages = parseImageRange(imageRange);
    const imageBlocks = splitImageBlocks(normalized, imageOverrides);
    const detectedImages = imageBlocks.map((block) => block.imageNumber);
    const detectedSet = new Set(detectedImages);
    const scopedDetectedImages = expectedImages.length
      ? detectedImages.filter((imageNumber) => expectedImages.includes(imageNumber))
      : detectedImages;
    const duplicateImages = detectedImages.filter((imageNumber, index) => detectedImages.indexOf(imageNumber) !== index);
    const missingMarkers = expectedImages.filter((imageNumber) => !detectedSet.has(imageNumber));
    const outOfRangeImages = expectedImages.length
      ? detectedImages.filter((imageNumber) => !expectedImages.includes(imageNumber))
      : [];
    const suspiciousStartRecords = findSuspiciousStartRecords(normalized, imageOverrides);

    return {
      ok: missingMarkers.length === 0 && duplicateImages.length === 0 && suspiciousStartRecords.length === 0,
      expectedImages,
      detectedImages,
      scopedDetectedImages,
      missingMarkers,
      duplicateImages: [...new Set(duplicateImages)],
      outOfRangeImages,
      suspiciousStartRecords,
    };
  }

  function splitEntries(sourceText, options = {}) {
    const normalized = sourceText.replace(/\r\n?/g, "\n");
    const imageRange = parseImageRange(options.imageRange || "");
    const imageBlocks = splitImageBlocks(normalized, options.imageOverrides || "");

    if (imageBlocks.length > 0) {
      return imageBlocks
        .filter((block) => imageRange.length === 0 || imageRange.includes(block.imageNumber))
        .flatMap((block) => splitEntriesInBlock(block.text, block.imageNumber));
    }

    return splitEntriesInBlock(normalized, "");
  }

  function splitImageBlocks(normalized, imageOverrides = "") {
    const markers = collectImageMarkers(normalized, imageOverrides);

    return markers.map((marker, index) => {
      const end = index + 1 < markers.length ? markers[index + 1].start : normalized.length;
      return {
        imageNumber: marker.imageNumber,
        text: normalized.slice(marker.start, end),
      };
    });
  }

  function collectImageMarkers(normalized, imageOverrides = "") {
    const normalMarkers = [...normalized.matchAll(startRecordPattern())].map((match) => ({
      imageNumber: normalizeImageNumber(match[1]),
      start: match.index + (match[0].startsWith("\n") ? 1 : 0),
      markerText: match[0].trim(),
    }));

    const overrideMarkers = parseImageOverrides(imageOverrides).flatMap((override) => {
      const markers = [];
      let start = 0;
      while (start < normalized.length) {
        const index = normalized.indexOf(override.markerText, start);
        if (index === -1) break;
        markers.push({
          imageNumber: override.imageNumber,
          start: index,
          markerText: override.markerText,
        });
        start = index + override.markerText.length;
      }
      return markers;
    });

    return [...normalMarkers, ...overrideMarkers]
      .sort((a, b) => a.start - b.start)
      .filter((marker, index, markers) => {
        const previous = markers[index - 1];
        return !previous || previous.start !== marker.start || previous.imageNumber !== marker.imageNumber;
      });
  }

  function splitEntriesInBlock(blockText, imageNumber) {
    const groupedEntries = splitGroupedEnglishEntries(blockText, imageNumber);
    const entryMatches = [...blockText.matchAll(entryHeadingPattern())];

    if (entryMatches.length === 0) {
      return mergeEntries(groupedEntries, splitLikelyEnglishEntriesInBlock(blockText, imageNumber));
    }

    const standardEntries = entryMatches.map((match, index) => {
      const start = match.index + (match[0].startsWith("\n") ? 1 : 0);
      const nextEntry = index + 1 < entryMatches.length ? entryMatches[index + 1].index : blockText.length;
      const nextStartRecord = findNextStartRecordIndex(blockText, start + match[0].length);
      const end = Math.min(nextEntry, nextStartRecord);
      const chunk = blockText.slice(start, end).trim();
      const lines = chunk.split("\n");
      let titleLine = lines[0] || "";
      let bodyLines = lines.slice(1);

      const bracketEntry = stripMarkdown(titleLine).match(/^\[Entry\s+(\d+)\]$/i);
      if (bracketEntry) {
        const nextLine = bodyLines[0] ? bodyLines[0].trim() : "";
        if (nextLine && !/^(?:Anno\s+Domini|In\s+the\s+year|\*\*|#{1,6})/i.test(nextLine)) {
          const embeddedStart = nextLine.search(/\.\s+(?:In\s+the\s+year\s+of\s+Our\s+Lord|Anno\s+Domini)\b/i);
          if (embeddedStart !== -1) {
            const namePart = stripMarkdown(nextLine.slice(0, embeddedStart));
            const remainingText = nextLine.slice(embeddedStart + 1).trim();
            titleLine = `Entry ${bracketEntry[1]}: ${namePart}`;
            bodyLines = [remainingText, ...bodyLines.slice(1)];
          } else {
            titleLine = `Entry ${bracketEntry[1]}: ${stripMarkdown(nextLine)}`;
            bodyLines = bodyLines.slice(1);
          }
        } else {
          titleLine = `Entry ${bracketEntry[1]}:`;
        }
      }

      return {
        title: stripMarkdown(titleLine),
        recordNumber: parseRecordNumber(titleLine),
        body: bodyLines.join("\n").trim(),
        imageNumber,
      };
    });

    return mergeEntries([...standardEntries, ...groupedEntries], splitLikelyEnglishEntriesInBlock(blockText, imageNumber));
  }

  function parseEntry(entry) {
    const english = getEntryEnglish(entry);
    if (!english) return null;

    const titleName = parseTitleName(entry.title);
    const dateParts = parseDate(english);
    const parents = parseParents(english);
    const child = parseChild(english, titleName);
    const godparents = parseGodparents(english);

    return {
      "Record #": entry.recordNumber || "",
      "Image #": entry.imageNumber || "",
      Year: dateParts.year,
      Date: dateParts.date,
      Child: child,
      "Child's Father": parents.father,
      "Child's Mother": parents.mother,
      "Godparent 1": godparents[0]?.name || "",
      "Godparent 1's Father": godparents[0]?.father || "",
      "Godparent 2": godparents[1]?.name || "",
      "Godparent 2's Father": godparents[1]?.father || "",
    };
  }

  function getEntryEnglish(entry) {
    return entry.englishOnly ? stripMarkdown(entry.body).trim() : extractEnglish(entry.body) || extractLikelyEnglish(entry.body);
  }

  function extractEnglish(body) {
    const match = body.match(/\*{0,2}English Translation:\*{0,2}\s*([\s\S]*?)(?=\n\s*\*{0,2}\s*(?:(?:Entry\s+)?\d+\s*[:.]|Transcription\s*(?:\(\s*Entry\s+\d+\s*:[^)]+\))?:?|English Translation:)|$)/i);
    return match ? stripMarkdown(match[1]).trim() : "";
  }

  function extractLikelyEnglish(body) {
    const cleaned = stripMarkdown(body).trim();
    if (!cleaned) return "";

    const englishStart = cleaned.search(/\bIn the year of Our Lord\b/i);
    if (englishStart === -1) return "";

    return cleaned.slice(englishStart).trim();
  }

  function findImageNumber(textBeforeEntry) {
    const matches = [...textBeforeEntry.matchAll(startRecordPattern())];
    return matches.length ? matches[matches.length - 1][1] : "";
  }

  function findSuspiciousStartRecords(normalized, imageOverrides = "") {
    const overrideLines = new Set(parseImageOverrides(imageOverrides).map((override) => override.markerText));
    const lines = normalized.split("\n");
    return lines
      .map((line, index) => ({ line: line.trim(), lineNumber: index + 1 }))
      .filter((item) => /START OF RECORD:/i.test(item.line) && !startRecordPattern().test(item.line) && !overrideLines.has(item.line));
  }

  function startRecordPattern() {
    return /(?:^|\n)\s*(?:---\s*)?START OF RECORD:\s*.*?_(\d+)\.[A-Za-z0-9]+(?:\s*---)?[^\n]*/gi;
  }

  function parseImageRange(rangeText) {
    const trimmed = String(rangeText || "").trim();
    if (!trimmed) return [];

    const images = [];
    for (const part of trimmed.split(/\s*,\s*/)) {
      const range = part.match(/^(\d+)\s*-\s*(\d+)$/);
      if (range) {
        const start = Number(range[1]);
        const end = Number(range[2]);
        const width = Math.max(3, range[1].length, range[2].length);
        for (let image = start; image <= end; image += 1) {
          images.push(normalizeImageNumber(String(image).padStart(width, "0")));
        }
        continue;
      }

      const single = part.match(/^(\d+)$/);
      if (single) images.push(normalizeImageNumber(single[1]));
    }

    return [...new Set(images)];
  }

  function parseImageOverrides(overridesText) {
    return String(overridesText || "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.match(/^(\d+)\s*[:=]\s*(.+)$/))
      .filter(Boolean)
      .map((match) => ({
        imageNumber: normalizeImageNumber(match[1]),
        markerText: match[2].trim(),
      }));
  }

  function normalizeImageNumber(imageNumber) {
    const trimmed = String(imageNumber || "").trim();
    return /^\d+$/.test(trimmed) ? trimmed.padStart(Math.max(3, trimmed.length), "0") : trimmed;
  }

  function findNextStartRecordIndex(text, fromIndex) {
    const nextText = text.slice(fromIndex);
    const match = nextText.match(/(?:^|\n)\s*(?:---\s*)?START OF RECORD:/i);
    return match ? fromIndex + match.index : text.length;
  }

  function parseRecordNumber(title) {
    const match = stripMarkdown(title).replace(/[\[\]]/g, "").match(/(?:Entry\s+)?(\d+)(?:\s*[:.]|\s*$)/i);
    return match ? match[1] : "";
  }

  function parseTitleName(title) {
    const cleaned = stripMarkdown(title).replace(/[\[\]]/g, "").replace(/\)+$/g, "");
    const match = cleaned.match(/(?:(?:Entry\s+)?\d+|Unnumbered\s+Entry)\s*:\s*(.+)$/i);
    if (match) return formatName(match[1]);
    if (/\b(?:Entry|Page|Left|Right|Fragment|\d)\b/i.test(cleaned)) return "";
    return formatName(cleaned);
  }

  function entryHeadingPattern() {
    return /(?:^|\n)\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:(?:Entry\s+\d+\s*(?:[:.][^\n]*)?|(?:\d+|Unnumbered\s+Entry)\s*:[^\n]*)|\[[^\]]*Entry\s+\d+[^\]]*\][^\n]*|Transcription\s*\(\s*Entry\s+\d+\s*:[^)]+\)\s*)(?:\*\*)?/gi;
  }

  function splitGroupedEnglishEntries(blockText, imageNumber) {
    const sectionMatches = [...blockText.matchAll(/(?:^|\n)\s*#{1,6}\s*\*{0,2}.*ENGLISH TRANSLATION.*\*{0,2}\s*$/gim)];

    return sectionMatches.flatMap((sectionMatch, sectionIndex) => {
      const sectionStart = sectionMatch.index + sectionMatch[0].length;
      const nextEnglishSection = sectionIndex + 1 < sectionMatches.length ? sectionMatches[sectionIndex + 1].index : blockText.length;
      const nextTranscription = blockText.slice(sectionStart, nextEnglishSection).search(/(?:^|\n)\s*#{1,6}\s*\*{0,2}.*TRANSCRIPTION.*\*{0,2}\s*$/im);
      const sectionEnd = nextTranscription >= 0 ? sectionStart + nextTranscription : nextEnglishSection;
      const sectionText = blockText.slice(sectionStart, sectionEnd);
      const titleMatches = [...sectionText.matchAll(/(?:^|\n)\s*\*\*([^*\n]+?)\*\*\s*(?=\n)/g)];

      return titleMatches
        .filter((match) => !/TRANSLATION|TRANSCRIPTION|PAGE|FILE/i.test(match[1]))
        .map((match, index) => {
          const start = match.index + (match[0].startsWith("\n") ? 1 : 0);
          const nextTitle = index + 1 < titleMatches.length ? titleMatches[index + 1].index : sectionText.length;
          const chunk = sectionText.slice(start, nextTitle).trim();
          const [title = "", ...rest] = chunk.split("\n");
          return {
            title: stripMarkdown(title),
            recordNumber: parseRecordNumber(title),
            body: rest.join("\n").trim(),
            imageNumber,
            englishOnly: true,
          };
        });
    });
  }

  function splitLikelyEnglishEntriesInBlock(blockText, imageNumber) {
    const cleanedBlock = stripMarkdown(blockText);
    const matches = [...cleanedBlock.matchAll(/(?:^|\n)\s*In the year of Our Lord\b/gim)];

    return matches.map((match, index) => {
      const start = match.index + (match[0].startsWith("\n") ? 1 : 0);
      const nextEnglish = index + 1 < matches.length ? matches[index + 1].index : cleanedBlock.length;
      const nextStartRecord = findNextStartRecordIndex(cleanedBlock, start + match[0].length);
      const nextLatin = findNextLatinEntryIndex(cleanedBlock, start + match[0].length);
      const end = Math.min(nextEnglish, nextStartRecord, nextLatin);

      return {
        title: "",
        recordNumber: "",
        body: cleanedBlock.slice(start, end).trim(),
        imageNumber,
        englishOnly: true,
      };
    });
  }

  function findNextLatinEntryIndex(text, fromIndex) {
    const nextText = text.slice(fromIndex);
    const match = nextText.match(/(?:^|\n)\s*Anno Domini\b/i);
    return match ? fromIndex + match.index : text.length;
  }

  function mergeEntries(primaryEntries, fallbackEntries) {
    const entries = [...primaryEntries];

    fallbackEntries.forEach((fallback) => {
      const fallbackSnippet = normalizeEntryText(fallback.body).slice(0, 120);
      const alreadyCaptured = entries.some((entry) => {
        const entryText = normalizeEntryText(entry.body);
        return fallbackSnippet && entryText.includes(fallbackSnippet);
      });
      if (!alreadyCaptured) entries.push(fallback);
    });

    return entries;
  }

  function normalizeEntryText(text) {
    return stripMarkdown(text).replace(/\s+/g, " ").trim().toLowerCase();
  }

  function buildExceptionLog(sourceText, options, imageCheck, parsedEntries) {
    const normalized = sourceText.replace(/\r\n?/g, "\n");
    const expectedImages = parseImageRange(options.imageRange || "");
    const imageBlocks = splitImageBlocks(normalized, options.imageOverrides || "")
      .filter((block) => expectedImages.length === 0 || expectedImages.includes(block.imageNumber));
    const rowsByImage = countRowsByImage(parsedEntries);
    const lines = [];

    imageBlocks.forEach((block) => {
      const rowCount = rowsByImage.get(block.imageNumber) || 0;
      if (rowCount === 0) {
        if (/\bIn the year of Our Lord\b/i.test(block.text)) {
          lines.push(`Image ${block.imageNumber}: contains English entry text but produced no PSV rows.`);
        } else {
          lines.push(`Image ${block.imageNumber}: no English entries were converted.`);
        }
      }
    });

    parsedEntries.forEach((item) => {
      if (containsLatinMarker(item.english)) {
        const imageNumber = item.row["Image #"] || "unknown";
        const recordNumber = item.row["Record #"] || "blank";
        lines.push(`Image ${imageNumber}, record ${recordNumber}: converted entry may include Latin transcription text.`);
      }
    });

    imageCheck.outOfRangeImages.forEach((imageNumber) => {
      lines.push(`Image ${imageNumber}: marker exists outside the requested range.`);
    });

    return lines;
  }

  function countRowsByImage(parsedEntries) {
    return parsedEntries.reduce((counts, item) => {
      const imageNumber = item.row["Image #"];
      counts.set(imageNumber, (counts.get(imageNumber) || 0) + 1);
      return counts;
    }, new Map());
  }

  function containsLatinMarker(text) {
    return /\bAnno Domini\b/i.test(text);
  }

  function parseDate(text) {
    const year = parseYear(text);
    const numericDate = text.match(/\b(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+(?:the\s+month\s+of\s+)?)?(January|February|March|April|May|June|July|August|September|October|November|December)\b/i);
    if (numericDate) {
      return { year, date: `${Number(numericDate[1])} ${capitalize(numericDate[2])}` };
    }

    const ordinalDate = text.match(/\b(?:on\s+)?(?:the\s+)?([a-z -]+?)\s+(?:day\s+of\s+(?:the\s+month\s+of\s+)?)?(January|February|March|April|May|June|July|August|September|October|November|December)\b/i);
    if (ordinalDate) {
      const day = ORDINALS[ordinalDate[1].trim().toLowerCase()];
      if (day) return { year, date: `${day} ${capitalize(ordinalDate[2])}` };
    }

    return { year, date: "" };
  }

  function parseYear(text) {
    const numeric = text.match(/\b(16|17|18|19)\d{2}\b/);
    if (numeric) return numeric[0];

    const phrase = text.match(/(?:year of Our Lord|Anno Domini)\s+([^.]+)/i);
    if (!phrase) return "";

    const year = wordsToNumber(phrase[1]);
    return year >= 1000 ? String(year) : "";
  }

  function wordsToNumber(phrase) {
    const tokens = phrase
      .toLowerCase()
      .replace(/-/g, " ")
      .replace(/,/g, "")
      .replace(/\band\b/g, " ")
      .split(/\s+/)
      .filter(Boolean);

    let total = 0;
    let current = 0;
    for (const token of tokens) {
      if (NUMBER_WORDS[token] !== undefined) {
        current += NUMBER_WORDS[token];
      } else if (token === "hundred") {
        current *= 100;
      } else if (token === "thousand") {
        total += current * 1000;
        current = 0;
      }
    }
    return total + current;
  }

  function parseParents(text) {
    const patterns = [
      /born[^.;]*?\bto the spouses\s+([A-Z][A-Za-z'’ -]+?)\s+and\s+([A-Z][A-Za-z'’ -]+?)(?:\s+of\s+this\s+land|\s+from|\s+of|;|,|\.)/i,
      /born to the spouses\s+(.+?)\s+and\s+(.+?)(?:\s+from|\s+of|;|,|\.)/i,
      /(?:born [^.]*?\s+)?to\s+([A-Z][A-Za-z'’ -]+?)\s+and\s+([A-Z][A-Za-z'’ -]+?)(?:\s+from\s+[^,;.]+)?(?:,\s+[^.;]*?\bspouses|\s+spouses)/i,
      /(?:born [^.]*?\s+)?to\s+([A-Z][A-Za-z'’ -]+?)\s+and\s+([A-Z][A-Za-z'’ -]+?)(?:,\s*spouses|\s+spouses)/i,
      /\bto\s+([A-Z][A-Za-z'' -]+?)\s+and\s+([A-Z][A-Za-z'' -]+?)(?=\s*(?:,|\bof\b|\bfrom\b|[;.]))/i,
      /(?:son|daughter|child)\s+of\s+(.+?)\s+and\s+(.+?)(?:\s+from|\s+of|;|,|\.)/i,
    ];

    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) {
        return {
          father: formatName(cleanName(match[1])),
          mother: formatName(cleanName(match[2])),
        };
      }
    }

    return { father: "", mother: "" };
  }

  function parseChild(text, titleName) {
    const nameGiven = text.match(/(?:was given the name|given the name)\s+([A-Z][A-Za-z' -]+?)(?=\s*[.,]|\s*$)/i);
    if (nameGiven) {
      const given = cleanName(nameGiven[1]);
      const surname = titleName ? titleName.split(",")[0] : "";
      return surname ? `${surname}, ${given}` : given;
    }
    return titleName;
  }

  function parseGodparents(text) {
    const clauses = [...text.matchAll(/\b(?:the\s+)?(godmother|godfather|sponsor)(?:\s+\([^)]+\))?\s+was\s+([\s\S]*?)(?=,\s+and\s+the\s+(?:godmother|godfather|sponsor)(?:\s+\([^)]+\))?\s+was\b|\.|;)/gi)].map((match) => parseGodparentClause(match[2]));
    const spouseClause = clauses.find((clause) => clause.spouse);

    if (spouseClause && clauses.length > 1) {
      return [
        { name: spouseClause.name, father: "" },
        { name: spouseClause.spouse, father: "" },
      ];
    }

    return clauses.flatMap((clause) => {
      const godparents = [{ name: clause.name, father: clause.father }];
      if (clause.spouse) godparents.push({ name: clause.spouse, father: "" });
      return godparents;
    });
  }

  function parseGodparentClause(detail) {
    const proxy = detail.match(/\b(?:acting as proxy for|on behalf of)\s+([A-Z][A-Za-z'’ -]+?)(?:\s+from|\s+of|$|,)/i);
    const father = detail.match(/,\s+(?:son|daughter)\s+of\s+(?:the\s+late\s+)?([A-Z][A-Za-z'’ -]+?)(?:\s+from|\s+of|$|,)/i);
    const spouse = detail.match(/,\s+(?:husband|wife)\s+of\s+([A-Z][A-Za-z'’ -]+?)(?:\s+from|\s+of|$|,)/i);
    const godparentName = proxy
      ? proxy[1]
      : detail
          .split(/,\s+(?:husband|wife|son|daughter)\s+of\b/i)[0]
          .replace(/\bfor this purpose\b/i, "")
          .replace(/\s+from\s+.+$/i, "")
          .replace(/\s+of\s+Rend[ei]$/i, "")
          .trim();

    return {
      name: formatName(cleanName(godparentName)),
      father: father && !proxy ? formatName(cleanName(father[1], surnameFrom(godparentName))) : "",
      spouse: spouse && !proxy ? formatName(cleanName(spouse[1])) : "",
    };
  }

  function formatName(rawName, fallbackSurname = "") {
    const cleaned = cleanName(rawName);
    if (!cleaned) return "";
    if (cleaned.includes(",")) return cleaned;

    const tokens = cleaned.split(/\s+/).filter(Boolean);
    if (tokens.length === 1) {
      return fallbackSurname ? `${fallbackSurname}, ${tokens[0]}` : tokens[0];
    }

    let surnameStart = tokens.length - 1;
    const previous = tokens[tokens.length - 2]?.toLowerCase();
    if (SURNAME_PREFIXES.has(previous)) surnameStart = tokens.length - 2;

    const surname = tokens.slice(surnameStart).join(" ");
    const given = tokens.slice(0, surnameStart).join(" ");
    return given ? `${surname}, ${given}` : surname;
  }

  function surnameFrom(rawName) {
    const formatted = formatName(rawName);
    return formatted.includes(",") ? formatted.split(",")[0] : "";
  }

  function cleanName(name, fallbackSurname = "") {
    if (!name) return "";
    const cleaned = name
      .replace(/\b(?:the\s+)?(?:late|deceased|quondam)\b/gi, "")
      .replace(/\b(?:Mr|Mrs|Miss|Don|Donna|Lord|Master|Lady|magnificent)\.?\b/gi, "")
      .replace(/\bthe\b/gi, "")
      .replace(/\b(?:acting as proxy for|on behalf of)\s+[A-Z][A-Za-z'’ -]+$/i, "")
      .replace(/\bfor this purpose$/i, "")
      .replace(/\s+/g, " ")
      .replace(/[.;:]+$/g, "")
      .trim();

    if (fallbackSurname && cleaned.split(/\s+/).length === 1) {
      return `${cleaned} ${fallbackSurname}`;
    }
    return cleaned;
  }

  function stripMarkdown(text) {
    return text.replace(/^#{1,6}\s*/gm, "").replace(/\*\*/g, "").trim();
  }

  function escapePsv(value) {
    return String(value || "").replace(/\|/g, "/").replace(/\s+/g, " ").trim();
  }

  function capitalize(value) {
    const month = MONTHS.find((candidate) => candidate.toLowerCase() === String(value).toLowerCase());
    return month || value;
  }

  window.BaptismPsvParser = { convertText, convertTextToPsv, splitEntries, parseEntry, verifyImageSequence };
})();
