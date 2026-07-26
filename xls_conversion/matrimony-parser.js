(function () {
  const HEADERS = [
    "Record #",
    "Image #",
    "Year",
    "Day/Mo",
    "Groom",
    "Bride",
    "Groom Parents/Widower",
    "Bride Parents/Widow",
    "From",
    "Testimoni",
    "Notes",
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

  const DEFAULT_CITY = "Rende";

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

  // -- Top-level conversion

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

  // -- Image sequence verification

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

  // -- Entry splitting

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
        if (nextLine && !/^(?:Anno\s+Domini|Year\s+of\s+the\s+Lord|\*\*|#{1,6})/i.test(nextLine)) {
          const embeddedStart = nextLine.search(/\.\s+(?:Year\s+of\s+the\s+Lord|Anno\s+Domini)\b/i);
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

  // -- Entry parsing

  function parseEntry(entry) {
    const english = getEntryEnglish(entry);
    if (!english) return null;

    const dateParts = parseDate(english);
    const entryCity = parseEntryCity(english);
    const couple = parseCouple(english);
    const from = parseFrom(couple.groomSection, couple.brideSection, entryCity);
    const testimoni = parseTestimoni(english, entryCity);

    return {
      "Record #": entry.recordNumber || "",
      "Image #": entry.imageNumber || "",
      "Year": dateParts.year,
      "Day/Mo": dateParts.date,
      "Groom": couple.groomName,
      "Bride": couple.brideName,
      "Groom Parents/Widower": couple.groomParents,
      "Bride Parents/Widow": couple.brideParents,
      "From": from,
      "Testimoni": testimoni,
      "Notes": "",
    };
  }

  function getEntryEnglish(entry) {
    return entry.englishOnly ? stripMarkdown(entry.body).trim() : extractEnglish(entry.body) || extractLikelyEnglish(entry.body);
  }

  function extractEnglish(body) {
    const match = body.match(/\*{0,2}(?:English\s+)?Translation:\*{0,2}\s*([\s\S]*?)(?=\n\s*\*{0,2}\s*(?:(?:Entry\s+)?\d+\s*[:.]|Transcription\s*(?:\(\s*Entry\s+\d+\s*:[^)]+\))?:?|(?:English\s+)?Translation:)|$)/i);
    return match ? stripMarkdown(match[1]).trim() : "";
  }

  function extractLikelyEnglish(body) {
    const cleaned = stripMarkdown(body).trim();
    if (!cleaned) return "";
    const start = cleaned.search(/\byear\s+of\s+(?:the|our)\s+Lord\b/i);
    if (start === -1) return "";
    return cleaned.slice(start).trim();
  }

  // -- Field parsers

  function parseDate(text) {
    const year = parseYear(text);
    const numericDate = text.match(/\bon\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of(?:\s+the\s+month\s+of)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b/i);
    if (numericDate) {
      return { year, date: `${Number(numericDate[1])} ${capitalize(numericDate[2])}` };
    }
    const ordinalDate = text.match(/\bon\s+the\s+([a-z][a-z -]+?)\s+day\s+of(?:\s+the\s+month\s+of)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b/i);
    if (ordinalDate) {
      const day = ORDINALS[ordinalDate[1].trim().toLowerCase()];
      if (day) return { year, date: `${day} ${capitalize(ordinalDate[2])}` };
    }
    return { year, date: "" };
  }

  function parseYear(text) {
    const numeric = text.match(/\b(1[6-9]\d{2})\b/);
    if (numeric) return numeric[1];
    const phrase = text.match(/Year\s+of\s+the\s+Lord\s+([^,.\n]+)/i);
    if (!phrase) return "";
    const year = wordsToNumber(phrase[1]);
    return year >= 1000 ? String(year) : "";
  }

  function parseCouple(text) {
    // Capture from "questioned/interrogated" up to the mutual-consent / joining clause.
    // The termination pattern covers both active and passive voice variants.
    const sectionMatch = text.match(
      /(?:solemnly\s+)?(?:questioned|interrogated)\s+([\s\S]+?)(?=\s*,?\s*(?:and\s+having\s+obtained\s+their\s+mutual\s+consent|having\s+obtained\s+their\s+mutual\s+consent|their\s+mutual\s+consent\s+having\s+been\s+obtained|the\s+spouses\s+having\s+first\s+confessed|and\s+they\s+having\s+first\s+confessed|I\s+joined\s+them|he\s+joined\s+them\b))/i
    );

    // Fallback: if the termination clause isn't recognized, grab from the action verb
    // to the end of the same sentence so names can still be extracted.
    let section;
    if (sectionMatch) {
      section = sectionMatch[1].trim();
    } else {
      const fallback = text.match(/(?:questioned|interrogated)\s+([\s\S]+?)(?=\.\s|\.$)/i);
      if (!fallback) return emptyCouple();
      section = fallback[1].trim();
    }

    // Primary split: ", and [Name], (son|daughter|widower|widow) of"
    let splitPos = section.search(/,\s+and\s+[A-Z][A-Za-z'' ]+?,\s+(?:son|daughter|widower|widow)\s+of\b/i);
    // Fallback: ", and [Capital Name]" — no parentage stated
    if (splitPos === -1) splitPos = section.search(/,\s+and\s+[A-Z][A-Za-z'']/);
    // Last resort: plain " and [Capital Name]" — no comma before "and"
    if (splitPos === -1) splitPos = section.search(/\s+and\s+[A-Z][A-Za-z'']/);
    if (splitPos === -1) return { ...emptyCouple(), groomSection: section };

    const groomSection = section.slice(0, splitPos).trim();
    const brideSection = section.slice(splitPos).replace(/^,?\s+and\s+/, "").trim();

    const groomName = extractPersonName(groomSection);
    const brideName = extractPersonName(brideSection);

    return {
      groomName,
      brideName,
      groomParents: extractParentage(groomSection, groomName, "son", "widower"),
      brideParents: extractParentage(brideSection, brideName, "daughter", "widow"),
      groomSection,
      brideSection,
    };
  }

  function emptyCouple() {
    return { groomName: "", brideName: "", groomParents: "", brideParents: "", groomSection: "", brideSection: "" };
  }

  function extractPersonName(section) {
    const nameMatch = section.match(/^([A-Z][A-Za-z'' ]+?),?\s+(?:son|daughter|widower|widow)\s+of\b/i);
    if (nameMatch) return formatName(nameMatch[1].trim());
    // Strip trailing location phrase before extracting name
    const stripped = stripTrailingLocation(section);
    const firstComma = stripped.indexOf(",");
    if (firstComma > 0) return formatName(stripped.slice(0, firstComma).trim());
    return formatName(stripped.trim());
  }

  function stripTrailingLocation(text) {
    return text
      .replace(/\s+of\s+(?:this\s+(?:same\s+)?|the\s+)?(?:city|town|village|place|land)\s+of\s+[A-Za-z'' ]+$/i, "")
      .replace(/\s+of\s+(?:this\s+(?:same\s+)?|the\s+)?(?:city|town|village|place|land)$/i, "")
      .replace(/\s+from\s+[A-Za-z'' ]+$/i, "")
      .trim();
  }

  function extractParentage(section, personName, childWord, widowWord) {
    // Stop characters: whitespace+of, whitespace+from, comma, semicolon, or end
    const stop = "(?:\\s+of\\s+|\\s+from\\s+|[,;]|$)";

    // Widower / widow of a previous spouse
    const widowPattern = new RegExp(
      `\\b${widowWord}\\s+of\\s+([A-Z][A-Za-z'' ]+?)${stop}`,
      "i"
    );
    const widowMatch = section.match(widowPattern);
    if (widowMatch && /^[A-Z]/i.test(widowMatch[1])) {
      const prefix = widowWord === "widower" ? "vedovo" : "vedova";
      const name = widowMatch[1].trim();
      if (/^[A-Z]/.test(name)) return `${prefix} ${formatName(name)}`;
    }

    // Normal parentage: "son/daughter of [the late] [Name]"
    const parentPattern = new RegExp(
      `\\b${childWord}\\s+of\\s+(the\\s+late\\s+)?([A-Z][A-Za-z'' ]+?)${stop}`,
      "i"
    );
    const parentMatch = section.match(parentPattern);
    if (!parentMatch) return "";
    if (!/^[A-Z]/.test(parentMatch[2])) return "";

    const isDeceased = !!parentMatch[1];
    const parentGiven = parentMatch[2].trim();
    const tokens = parentGiven.split(/\s+/);
    let parentFormatted;
    if (tokens.length === 1) {
      // Only a given name — infer surname from the child
      const personSurname = surnameFrom(personName);
      parentFormatted = personSurname ? `${personSurname}, ${parentGiven}` : parentGiven;
    } else {
      parentFormatted = formatName(parentGiven);
    }
    return isDeceased ? `${parentFormatted} (fu)` : parentFormatted;
  }

  function parseEntryCity(text) {
    // "...Month, City." — city directly capitalized after the comma (no /i so [A-Z] requires uppercase)
    const direct = text.match(/\bon\s+the\s+.+?(?:January|February|March|April|May|June|July|August|September|October|November|December)\b[^.]*,\s+([A-Z][A-Za-z'' ]+?)\s*[.,]/);
    if (direct) return direct[1].trim();
    // "...Month, in City." — city preceded by the preposition "in"
    const withIn = text.match(/\bon\s+the\s+.+?(?:January|February|March|April|May|June|July|August|September|October|November|December)\b[^.]*,\s+in\s+([A-Z][A-Za-z'' ]+?)\s*[.,]/i);
    if (withIn && /^[A-Z]/.test(withIn[1])) return withIn[1].trim();
    return "";
  }

  function parseFrom(groomSection, brideSection, entryCity = "") {
    const groomLoc = extractLocation(groomSection, entryCity);
    const brideLoc = extractLocation(brideSection, entryCity);

    if (groomLoc && brideLoc) return `${groomLoc}, ${brideLoc}`;

    const sharedLoc = brideLoc || groomLoc;
    if (!sharedLoc) return "";

    // "of this [same] city/town/place" signals that the location applies to both parties
    const sourceSection = brideLoc ? brideSection : groomSection;
    const isShared = /\bof\s+this\s+(?:same\s+)?(?:city|town|place|land)\b/i.test(sourceSection);
    return isShared ? `${sharedLoc}, ${sharedLoc}` : sharedLoc;
  }

  function extractLocation(section, fallbackCity = "") {
    if (!section) return "";
    // All patterns use /i for keyword matching, but captured names are validated for true uppercase start
    const thisNamedCity = section.match(/\bof\s+this\s+(?:same\s+)?(?:city|town|place|land)\s+of\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,.]|$)/i);
    if (thisNamedCity && /^[A-Z]/.test(thisNamedCity[1])) return thisNamedCity[1].trim();
    const namedCity = section.match(/\bof\s+the\s+(?:city|town|village)\s+of\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,.]|$)/i);
    if (namedCity && /^[A-Z]/.test(namedCity[1])) return namedCity[1].trim();
    const fromPlace = section.match(/\bfrom\s+(?:the\s+(?:city|town|village)\s+of\s+)?([A-Z][A-Za-z'' ]+?)(?:\s*[,.]|$)/i);
    if (fromPlace && /^[A-Z]/.test(fromPlace[1])) return fromPlace[1].trim();
    // "of this [same] City" without a named city — use the entry city or the register default
    if (/\bof\s+this\s+(?:same\s+)?(?:city|town|place|land)\b/i.test(section)) return fallbackCity || DEFAULT_CITY;
    return "";
  }

  function parseTestimoni(text, entryCity = "") {
    const witnessMatch = text.match(
      /(?:present\s+as\s+witnesses?|in\s+the\s+presence\s+of\s+(?:the\s+)?witnesses?)\s+([\s\S]+?)(?=\s*(?:,?\s+and\s+(?:others|in\s+faith)\b|,\s+in\s+faith\b|\.\s*(?:\n|$)|\n))/i
    );
    if (!witnessMatch) return "";

    const raw = witnessMatch[1].replace(/\s+and\s+others(?:\s+known\s+to\s+me)?\s*$/i, "").trim();
    const parts = raw
      .split(/\s*,\s+and\s+|\s+and\s+(?=[A-Z])|\s*,\s+(?=[A-Z])/)
      .map((w) => w.trim())
      .filter(Boolean);

    return parts.map((w) => formatName(stripTrailingLocation(w))).join("; ");
  }

  // -- Entry text helpers

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
    const matches = [...cleanedBlock.matchAll(/(?:^|\n)\s*(?:In\s+the\s+)?year\s+of\s+(?:the|our)\s+Lord\b/gim)];

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
        if (/\byear\s+of\s+(?:the|our)\s+Lord\b/i.test(block.text)) {
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

  // -- Structural patterns

  function startRecordPattern() {
    return /(?:^|\n)\s*(?:---\s*)?START OF RECORD:\s*.*?_(\d+)\.[A-Za-z0-9]+(?:\s*---)?[^\n]*/gi;
  }

  function entryHeadingPattern() {
    return /(?:^|\n)\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:Entry\s+\d+\s*(?::[^\n]*|\([^)]*\)[^\n]*|(?=\s*(?:\*\*)?\s*(?:\n|$)))|(?:\d+|Unnumbered\s+Entry)\s*(?::[^\n]*|\([^)]*\)[^\n]*)|\[[^\]]*Entry\s+\d+[^\]]*\][^\n]*|Transcription\s*\(\s*Entry\s+\d+\s*:[^)]+\)\s*)(?:\*\*)?/gi;
  }

  function findNextStartRecordIndex(text, fromIndex) {
    const nextText = text.slice(fromIndex);
    const match = nextText.match(/(?:^|\n)\s*(?:---\s*)?START OF RECORD:/i);
    return match ? fromIndex + match.index : text.length;
  }

  function findSuspiciousStartRecords(normalized, imageOverrides = "") {
    const overrideLines = new Set(parseImageOverrides(imageOverrides).map((override) => override.markerText));
    const lines = normalized.split("\n");
    return lines
      .map((line, index) => ({ line: line.trim(), lineNumber: index + 1 }))
      .filter((item) => /START OF RECORD:/i.test(item.line) && !startRecordPattern().test(item.line) && !overrideLines.has(item.line));
  }

  function parseRecordNumber(title) {
    const cleaned = stripMarkdown(title).replace(/[\[\]]/g, "");
    const withColon = cleaned.match(/(?:Entry\s+)?(\d+)\s*[:.]/i);
    if (withColon) return withColon[1];
    const withParen = cleaned.match(/\bEntry\s+(\d+)\s*\(/i);
    if (withParen) return withParen[1];
    const plain = cleaned.match(/\bEntry\s+(\d+)\s*$/i);
    if (plain) return plain[1];
    return "";
  }

  function parseTitleName(title) {
    const cleaned = stripMarkdown(title).replace(/[\[\]]/g, "").replace(/\)+$/g, "");
    const match = cleaned.match(/(?:(?:Entry\s+)?\d+|Unnumbered\s+Entry)\s*:\s*(.+)$/i);
    if (match) return formatName(match[1]);
    if (/\b(?:Entry|Page|Left|Right|Fragment|\d)\b/i.test(cleaned)) return "";
    return formatName(cleaned);
  }

  // -- Image range / override helpers

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

  // -- Name / text utilities

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
    return formatted.includes(",") ? formatted.split(",")[0].trim() : "";
  }

  function cleanName(name) {
    if (!name) return "";
    return name
      .replace(/\b(?:the\s+)?(?:late|deceased|quondam)\b/gi, "")
      .replace(/\b(?:Mr|Mrs|Miss|Don|Donna|Lord|Master|Lady|magnificent|Reverend)\.?\b/gi, "")
      .replace(/\bthe\b/gi, "")
      .replace(/\s+/g, " ")
      .replace(/[.;:]+$/g, "")
      .trim();
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

  window.MatrimonyPsvParser = { convertText, convertTextToPsv, splitEntries, parseEntry, verifyImageSequence };
})();
