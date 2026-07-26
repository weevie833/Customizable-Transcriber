(function () {
  const HEADERS = [
    "Record #",
    "Image #",
    "Year",
    "Date",
    "Deceased",
    "Father",
    "Mother",
    "Spouse",
    "Age",
    "Birth Year",
    "From",
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
    applyDateCarryForward(parsedEntries);
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
    const normalMarkers = [...normalized.matchAll(startRecordPattern())]
      .filter((match) => !/\bindex\b/i.test(match[0]))
      .map((match) => ({
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
    const deceased = parseDeceased(english);
    const father = parseFather(english, deceased);
    const mother = parseMother(english, deceased);
    const spouse = parseSpouseOfDeceased(english);
    const age = parseAge(english);
    const birthYear = calcBirthYear(dateParts.year, age);
    const from = parseFrom(english, entryCity);

    return {
      "Record #": entry.recordNumber || "",
      "Image #": entry.imageNumber || "",
      "Year": dateParts.year,
      "Date": dateParts.date,
      "Deceased": deceased,
      "Father": father,
      "Mother": mother,
      "Spouse": spouse,
      "Age": age,
      "Birth Year": birthYear,
      "From": from,
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

    // Numeric day: "on the [day <adverb> the] Nth [day] of [the month of] Month"
    const numericDate = text.match(
      /\bon\s+the\s+(?:day\s+\w+\s+the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+)?of(?:\s+the\s+month\s+of)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b/i
    );
    if (numericDate) {
      return { year, date: `${Number(numericDate[1])} ${capitalize(numericDate[2])}` };
    }

    // Ordinal word: "on the [day <adverb> the] [ordinal] [day] of [the month of] Month"
    const ordinalDate = text.match(
      /\bon\s+the\s+(?:day\s+\w+\s+the\s+)?([a-z][a-z -]+?)\s+(?:day\s+)?of(?:\s+the\s+month\s+of)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b/i
    );
    if (ordinalDate) {
      const day = ORDINALS[ordinalDate[1].trim().toLowerCase()];
      if (day) return { year, date: `${day} ${capitalize(ordinalDate[2])}` };
    }

    return { year, date: "" };
  }

  function parseYear(text) {
    const numeric = text.match(/\b(1[6-9]\d{2})\b/);
    if (numeric) return numeric[1];
    // "Year of the Lord [words]" or "Year [words]" (some scribes omit "of the Lord")
    const phrase = text.match(/\bYear\s+(?:of\s+(?:the|our)\s+Lord\s+)?([^.\n]+?)(?=\s*,?\s*on\s+the\s+|\s*[.\n]|$)/i);
    if (!phrase) return "";
    const year = wordsToNumber(phrase[1]);
    return year >= 1000 ? String(year) : "";
  }

  function parseDeceased(text) {
    let section = extractAfterDate(text);
    if (!section) return "";

    // Strip leading location phrase: "In Rende was Angela..." → "Angela..."
    // Requires actual uppercase place name (no i flag on character class)
    section = section.replace(/^(?:In|At|From)\s+[A-Z][A-Za-z'']+(?:\s+[A-Z][A-Za-z'']+)?\s+was\s+/, "");
    // Strip inline origin suffix: "Pasquale Tavernaro from Castiglione," → "Pasquale Tavernaro,"
    section = section.replace(/\s+from\s+[A-Z][A-Za-z'']+(?:\s+[A-Z][A-Za-z'']+)?\s*(?=[,;.])/i, "");

    // Names in these records never contain commas — stop at the first comma or semicolon
    const stopIndex = section.search(/[,;]/);
    const nameText = stopIndex > 0 ? section.slice(0, stopIndex) : section.split(/\./)[0];
    return formatName(nameText.trim());
  }

  function extractAfterDate(text) {
    const MONTH = /(?:January|February|March|April|May|June|July|August|September|October|November|December)\b/i;
    const monthMatch = text.match(MONTH);

    if (monthMatch) {
      const rest = text.slice(monthMatch.index + monthMatch[0].length);
      // ". [City.]" — period, then optionally a bare city word ending with a period
      const periodTail = rest.match(/^\s*\.(?:\s*[A-Z][A-Za-z'']{1,25}\.)?\s*/);
      if (periodTail) return rest.slice(periodTail[0].length).trim();
      // ";" — semicolon directly into body
      const semiTail = rest.match(/^\s*;/);
      if (semiTail) return rest.slice(semiTail[0].length).trim();
      // ", City." — comma followed by a single capitalized city word and a period
      const cityTail = rest.match(/^\s*,\s*[A-Z][A-Za-z'']{1,25}\.\s*/);
      if (cityTail) return rest.slice(cityTail[0].length).trim();
      // ", in/at City." or ", in/at City," — preposition before city name
      const prepCityTail = rest.match(/^\s*,\s*(?:in|at)\s+[A-Z][A-Za-z'']{1,25}[.,]\s*/i);
      if (prepCityTail) return rest.slice(prepCityTail[0].length).trim();
      // ", body" — comma directly into the deceased name (no city)
      const commaTail = rest.match(/^\s*,\s*/);
      if (commaTail) return rest.slice(commaTail[0].length).trim();
      return rest.trim();
    }

    // Fallback: no month stated — date ends with an ordinal and period ("...the twenty-second.")
    const ordinalMatch = text.match(
      /\bon\s+the\s+(?:day\s+\w+\s+the\s+)?(?:\d{1,2}(?:st|nd|rd|th)?|[a-z][a-z -]+?)\s*\.(?:\s*[A-Z][A-Za-z'']{1,30}\.)?/i
    );
    if (ordinalMatch) return text.slice(ordinalMatch.index + ordinalMatch[0].length).trim();

    return "";
  }

  function parseFather(text, deceasedName) {
    // Two parents: "born of [Father] and [Mother]" — father is the first name
    const bornOf = text.match(/\bborn\s+of\s+([A-Z][A-Za-z'' ]+?)\s+and\s+[A-Z]/i);
    if (bornOf) {
      const name = bornOf[1].trim();
      if (name.split(/\s+/).length === 1) {
        const deceasedSurname = surnameFrom(deceasedName);
        return deceasedSurname ? `${deceasedSurname}, ${name}` : name;
      }
      return formatName(name);
    }

    // Parent with grandparent: "son/daughter of [Parent] son/daughter of [Grandparent]"
    const withGrandparent = text.match(
      /\b(?:son|daughter)\s+of\s+(the\s+late\s+)?([A-Z][A-Za-z'' ]+?)\s+(son|daughter)\s+of\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,;.]|\s+of\s+|\s+from\s+|\s+in\s+|$)/i
    );
    if (withGrandparent && /^[A-Z]/.test(withGrandparent[2])) {
      const isDeceased = !!withGrandparent[1];
      const parentGiven = withGrandparent[2].trim();
      const grandparentRel = withGrandparent[3].toLowerCase();
      const grandparentGiven = withGrandparent[4].trim();
      const deceasedSurname = surnameFrom(deceasedName);
      const parentFormatted = deceasedSurname ? `${deceasedSurname}, ${parentGiven}` : parentGiven;
      const base = isDeceased ? `${parentFormatted} (fu)` : parentFormatted;
      return `${base}, ${grandparentRel} of ${grandparentGiven}`;
    }

    // Single parent: "son/daughter of [the late] [Name]"
    const childOf = text.match(
      /\b(?:son|daughter)\s+of\s+(the\s+late\s+)?([A-Z][A-Za-z'' ]+?)(?:\s*[,;.]|\s+of\s+|\s+from\s+|\s+in\s+|$)/i
    );
    if (childOf && /^the\s+widow\b/i.test(childOf[2])) return ""; // widowed mother → parseMother
    if (childOf) {
      const isDeceased = !!childOf[1];
      const name = childOf[2].trim();
      const tokens = name.split(/\s+/);
      let formatted;
      if (tokens.length === 1) {
        const deceasedSurname = surnameFrom(deceasedName);
        formatted = deceasedSurname ? `${deceasedSurname}, ${name}` : name;
      } else {
        formatted = formatName(name);
      }
      return isDeceased ? `${formatted} (fu)` : formatted;
    }

    return "";
  }

  function parseMother(text, deceasedName) {
    // "son/daughter of the widow [Name]" — widowed mother listed as sole parent
    const singleMother = text.match(
      /\b(?:son|daughter)\s+of\s+the\s+widow\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,;.]|\s+of\s+|\s+from\s+|\s+in\s+|$)/i
    );
    if (singleMother && /^[A-Z]/.test(singleMother[1])) {
      const name = singleMother[1].trim();
      if (name.split(/\s+/).length === 1) {
        const deceasedSurname = surnameFrom(deceasedName);
        return deceasedSurname ? `${deceasedSurname}, ${name}` : name;
      }
      return formatName(name);
    }
    // Two parents: "born of [Father] and [Mother]" — mother is the second name
    const bornOf = text.match(
      /\bborn\s+of\s+[A-Z][A-Za-z'' ]+?\s+and\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,;.]|$)/i
    );
    if (bornOf) return formatName(bornOf[1].trim());
    return "";
  }

  function parseSpouseOfDeceased(text) {
    // "husband/wife/widow/widower of [the late] [Name]" — spouse of the deceased person
    const match = text.match(
      /\b(husband|wife|widow|widower)\s+of\s+(the\s+late\s+)?([A-Za-z'' ]+?)(?:\s*,\s*spouse\b|\s*[,;.]|$)/i
    );
    if (!match || !/^[A-Z]/.test(match[3])) return "";

    const relationship = match[1].toLowerCase();
    const isLate = !!match[2];
    const name = formatName(match[3].trim());

    if (relationship === "widow" || relationship === "widower") {
      return `${relationship} of ${name}`;
    }

    return isLate ? `${name} (fu)` : name;
  }

  function parseEntryCity(text) {
    // City appearing right after the date clause, separated by comma or period.
    // Captured as 1-2 capitalized words (no spaces within each word) to avoid
    // matching descriptive phrases like "The widow Maria Maddalena".
    const direct = text.match(
      /(?:January|February|March|April|May|June|July|August|September|October|November|December)\b[^.,]*[.,]\s*([A-Z][A-Za-z'']+(?:\s+[A-Z][A-Za-z'']+)?)\s*\./i
    );
    if (direct && /^[A-Z]/.test(direct[1])) return direct[1].trim();
    return "";
  }

  function parseAge(text) {
    // "of his/her/their age N years approximately"
    const ageOf = text.match(/\bof\s+(?:his|her|their)\s+age\s+(\w[\w -]*?)\s+years?\b/i);
    if (ageOf) return parseAgeValue(ageOf[1].trim());
    // "of approximately N years"
    const approxOf = text.match(/\bof\s+approximately\s+(\w[\w -]*?)\s+years?\b/i);
    if (approxOf) return parseAgeValue(approxOf[1].trim());
    // "of years N approximately"
    const yearsOf = text.match(/\bof\s+years?\s+(\w[\w -]*?)\s+approximately\b/i);
    if (yearsOf) return parseAgeValue(yearsOf[1].trim());
    // "of his/her/their age N approximately" — no "years" stated
    const ageNoYears = text.match(/\bof\s+(?:his|her|their)\s+age\s+(\w[\w -]*?)\s+approximately\b/i);
    if (ageNoYears) return parseAgeValue(ageNoYears[1].trim());
    // "of about N years"
    const aboutOf = text.match(/\bof\s+about\s+(\w[\w -]*?)\s+years?\b/i);
    if (aboutOf) return parseAgeValue(aboutOf[1].trim());
    // Infant keyword — age 0, birth year = death year (handled in calcBirthYear)
    if (/\binfant\b/i.test(text)) return "0";
    return "";
  }

  function parseAgeValue(raw) {
    if (/^\d+$/.test(raw)) return raw;
    const n = wordsToNumber(raw);
    return n > 0 ? String(n) : "";
  }

  function calcBirthYear(year, age) {
    if (!year || age === "") return "";
    const y = Number(year);
    const a = Number(age);
    if (isNaN(y) || isNaN(a)) return "";
    if (a === 0) return year; // infant: born same year as death
    return String(y - a);
  }

  function parseFrom(text, entryCity) {
    // "originally from X" explicitly names the deceased's origin — highest priority
    const originallyFrom = text.match(/\boriginally\s+from\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,.]|$)/i);
    if (originallyFrom && /^[A-Z]/.test(originallyFrom[1])) return originallyFrom[1].trim();
    // "from the land of X" or "the land of X"
    const landOf = text.match(/\b(?:from\s+)?the\s+land\s+of\s+([A-Z][A-Za-z'' ]+?)(?:\s*[,.]|$)/i);
    if (landOf && /^[A-Z]/.test(landOf[1])) return landOf[1].trim();
    // "Name from City," — origin stated inline after the deceased's name
    const inlineFrom = text.match(/\bfrom\s+([A-Z][A-Za-z'']{2,}(?:\s+[A-Z][A-Za-z'']+)?)\s*[,;]/);
    if (inlineFrom && /^[A-Z]/.test(inlineFrom[1])) return inlineFrom[1].trim();
    if (entryCity) return entryCity;
    return DEFAULT_CITY;
  }

  // -- Date carry-forward

  function applyDateCarryForward(parsedEntries) {
    let lastYear = "";
    let lastDate = "";
    let lastFrom = "";

    parsedEntries.forEach((item) => {
      const row = item.row;
      if (row["Year"]) lastYear = row["Year"];
      if (row["Date"]) lastDate = row["Date"];
      if (row["From"]) lastFrom = row["From"];
      if (!row["Date"] && lastDate && isSameDayEntry(item.english)) {
        if (!row["Year"]) row["Year"] = lastYear;
        row["Date"] = lastDate;
        if (!row["From"] && lastFrom) row["From"] = lastFrom;
      }
    });
  }

  function isSameDayEntry(english) {
    return /\bon\s+the\s+(?:same|aforementioned|aforesaid|said)\s+day\b/i.test(english);
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
      .replace(/\b(?:the\s+)?(?:late|deceased|quondam|widow|widower)\b/gi, "")
      .replace(/\b(?:Mr|Mrs|Miss|Don|Donna|Lord|Master|Lady|magnificent|Reverend|Blessed)\.?\b/gi, "")
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

  window.MortiPsvParser = { convertText, convertTextToPsv, splitEntries, parseEntry, verifyImageSequence };
})();
