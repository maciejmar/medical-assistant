"""Zestaw edukacyjnych dokumentów logopedycznych zasilających bazę wiedzy (Qdrant).

Materiały mają charakter pomocniczy i nie zastępują aktualnych wytycznych ani oceny klinicznej.
Kody ICD-11 podano tam, gdzie mają jednoznaczny odpowiednik w rozdziale 6A01 (zaburzenia rozwoju
mowy i języka); w pozostałych przypadkach pole jest puste, a kod należy zweryfikować w
przeglądarce klasyfikacji WHO.
"""

DOCUMENTS: list[dict[str, str]] = [
    # ---------------------------------------------------------------- jednostki chorobowe
    {
        "key": "rotacyzm",
        "title": "Rotacyzm (dyslalia głoski r)",
        "category": "disorder",
        "audience": "children",
        "icd10": "F80.0",
        "icd11": "6A01.0",
        "tags": "rotacyzm, r, dyslalia, artykulacja, deformacja, substytucja",
        "text": (
            "Rotacyzm to nieprawidłowa realizacja głoski r: może być zastępowana innymi głoskami "
            "(l, j, w, ł – paraplazm), wymawiana nieprawidłowo (r uwularne, gardłowe, "
            "jednouderzeniowe, policzkowe – rotacyzm właściwy) lub opuszczana (mogilalia). Głoska r "
            "kształtuje się najpóźniej, prawidłowo do 5.–6. roku życia; utrzymywanie się wady po "
            "6. roku życia wymaga terapii. Diagnostyka obejmuje ocenę sprawności języka (pionizacja, "
            "wibracja czubka języka), słuch fonemowy, budowę wędzidełka i zgryz. Przyczyny: krótkie "
            "wędzidełko, obniżone napięcie mięśni języka, wady zgryzu, niedostateczny słuch fonemowy."
        ),
    },
    {
        "key": "sygmatyzm",
        "title": "Sygmatyzm (seplenienie) i inne wady wymowy głosek szeregu syczącego",
        "category": "disorder",
        "audience": "children",
        "icd10": "F80.0",
        "icd11": "6A01.0",
        "tags": "sygmatyzm, seplenienie, s z c dz, sz ż cz dż, ś ź ć dź, międzyzębowe, boczne",
        "text": (
            "Sygmatyzm dotyczy głosek szeregu szumiącego, syczącego i ciszącego. Najczęstsze formy "
            "to seplenienie międzyzębowe (język wsuwany między zęby), boczne (powietrze ucieka "
            "bokami), przedniojęzykowo-zębowe (substytucja przez t, d) oraz nosowe. Normy wiekowe: "
            "głoski ś, ź, ć, dź powinny być opanowane ok. 3.–4. roku życia, s, z, c, dz ok. 4.–5., "
            "sz, ż, cz, dż ok. 5.–6. Terapia rozpoczyna się od usprawniania narządów artykulacyjnych "
            "i ćwiczeń oddechowych, następnie wywołuje się głoskę w izolacji, sylabach, słowach, "
            "zdaniach i mowie spontanicznej."
        ),
    },
    {
        "key": "afazja",
        "title": "Afazja (zaburzenia mowy pochodzenia korowego)",
        "category": "disorder",
        "audience": "adults",
        "icd10": "R47.0",
        "icd11": "",
        "tags": "afazja, Broca, Wernickego, globalna, anomiczna, udar, agramatyzm, parafazje",
        "text": (
            "Afazja to nabyte zaburzenie rozumienia i/lub wytwarzania mowy wskutek uszkodzenia "
            "ośrodkowego układu nerwowego, najczęściej po udarze niedokrwiennym lewej półkuli (także "
            "po urazie czaszkowo-mózgowym lub guzie). Afazja ruchowa (Broca): mowa niepłynna, "
            "wysiłkowa, agramatyzm, względnie zachowane rozumienie. Afazja czuciowa (Wernickego): "
            "mowa płynna, liczne parafazje i neologizmy, zaburzone rozumienie. Afazja globalna "
            "obejmuje głębokie zaburzenia obu modalności; afazja anomiczna – głównie trudności w "
            "nazywaniu. Następstwa udaru koduje się dodatkowo w grupie I69 (np. I69.3). Diagnostyka "
            "obejmuje ocenę spontanicznej mowy, rozumienia, powtarzania, nazywania, czytania i pisania. "
            "Zaburzenie wymaga współpracy z neurologiem i neuropsychologiem."
        ),
    },
    {
        "key": "dyzartria",
        "title": "Dyzartria (zaburzenia artykulacji pochodzenia neurologicznego)",
        "category": "disorder",
        "audience": "adults",
        "icd10": "R47.1",
        "icd11": "",
        "tags": "dyzartria, Parkinson, udar, SLA, stwardnienie rozsiane, wiotka, spastyczna, ataktyczna",
        "text": (
            "Dyzartria to zaburzenie realizacji mowy wynikające z osłabienia, porażenia lub "
            "niekoordynowanej pracy mięśni oddechowych, fonacyjnych i artykulacyjnych. Nie dotyczy "
            "funkcji językowych. Wg klasyfikacji Darley'a, Aronsona i Browna wyróżnia się typy: "
            "wiotki, spastyczny, ataktyczny, hipokinetyczny (choroba Parkinsona), hiperkinetyczny "
            "i mieszany. Objawy: nieprecyzyjna artykulacja, zmieniona głośność i melodia, "
            "hipernazalność, skrócone fonacje, zaburzona prozodia. Występuje po udarze, w chorobie "
            "Parkinsona, SLA, stwardnieniu rozsianym, porażeniu mózgowym. Ocena obejmuje badanie "
            "motoryki narządów mowy, oddychania, fonacji, rezonansu i zrozumiałości mowy."
        ),
    },
    {
        "key": "jakanie",
        "title": "Jąkanie (zaburzenie płynności mowy)",
        "category": "disorder",
        "audience": "all",
        "icd10": "F98.5",
        "icd11": "6A01.1",
        "tags": "jąkanie, płynność mowy, powtórzenia, blokady, przedłużenia, współruchy, lęk",
        "text": (
            "Jąkanie to zaburzenie płynności mowy z powtarzaniem głosek i sylab, przedłużeniami oraz "
            "blokadami, często z współruchami i unikaniem sytuacji komunikacyjnych. Rozwojowe jąkanie "
            "zaczyna się zwykle między 2. a 5. rokiem życia; u większości dzieci (wg różnych badań "
            "ok. 70–80%) ustępuje samoistnie, lecz czynnikami ryzyka przetrwania są: występowanie w "
            "rodzinie, płeć męska, utrzymywanie się objawów ponad 6–12 miesięcy oraz współistnienie "
            "napięcia i świadomości trudności. W ocenie liczy się odsetek zająknięć na 100 sylab, "
            "nasilenie napięcia oraz wpływ na komunikację i emocje. U dorosłych istotnym elementem "
            "jest lęk społeczny i unikanie wyrazów."
        ),
    },
    {
        "key": "mowa_bezladna",
        "title": "Mowa bezładna (tachylalia, cluttering)",
        "category": "disorder",
        "audience": "all",
        "icd10": "F98.6",
        "icd11": "6A01.1",
        "tags": "mowa bezładna, tachylalia, cluttering, szybkie tempo, zlewanie sylab",
        "text": (
            "Mowa bezładna to zaburzenie płynności charakteryzujące się szybkim i/lub nieregularnym "
            "tempem, zlewaniem lub opuszczaniem sylab, nieuporządkowaną składnią i słabą "
            "samokontrolą mowy. W przeciwieństwie do jąkania osoba często nie zauważa własnych "
            "trudności, a nasilenie zmniejsza się pod wpływem skupienia uwagi na mówieniu. Często "
            "współwystępuje z ADHD, trudnościami w pisaniu i zaburzeniami uwagi. Terapia obejmuje "
            "kontrolę tempa, rytmizację, ćwiczenia świadomości słuchowej i planowania wypowiedzi."
        ),
    },
    {
        "key": "opozniony_rozwoj_mowy",
        "title": "Opóźniony rozwój mowy i rozwojowe zaburzenie językowe (DLD)",
        "category": "disorder",
        "audience": "children",
        "icd10": "F80.1",
        "icd11": "6A01.2",
        "tags": "opóźniony rozwój mowy, ORM, DLD, SLI, zaburzenie ekspresywne, zaburzenie receptywne",
        "text": (
            "Opóźniony rozwój mowy oznacza późniejsze niż zakładają normy pojawianie się mowy "
            "czynnej lub biernej. Sygnały alarmowe: brak gaworzenia do 12. miesiąca, brak "
            "pojedynczych słów do 18. miesiąca, brak łączenia dwóch słów do 24. miesiąca, brak "
            "reakcji na imię. Klasyfikacja ICD-10: F80.1 – zaburzenie mowy ekspresywnej, F80.2 – "
            "zaburzenie rozumienia mowy (receptywne). W ICD-11 rozwojowe zaburzenia języka mieszczą "
            "się w 6A01.2. Diagnostyka różnicowa obejmuje niedosłuch, autyzm, niepełnosprawność "
            "intelektualną, afazję dziecięcą i deprywację środowiskową; zawsze zalecana jest "
            "audiometria oraz konsultacja neurologiczna lub psychologiczna."
        ),
    },
    {
        "key": "dysfonia",
        "title": "Dysfonia i zaburzenia głosu",
        "category": "disorder",
        "audience": "adults",
        "icd10": "R49.0",
        "icd11": "",
        "tags": "dysfonia, głos, chrypka, afonia, hiperfunkcjonalna, guzki głosowe, foniatra",
        "text": (
            "Dysfonia to zaburzenie fonacji objawiające się chrypką, zmęczeniem głosu, zmianą "
            "wysokości lub natężenia. Może mieć charakter organiczny (zmiany strun głosowych, "
            "porażenie fałdu), czynnościowy hiperfunkcjonalny lub hipofunkcjonalny albo "
            "psychogenny. Każda chrypka utrzymująca się powyżej 3–4 tygodni wymaga konsultacji "
            "laryngologiczno-foniatrycznej z wideolaryngoskopią, zanim rozpocznie się terapia "
            "logopedyczna. Terapia obejmuje higienę głosu, relaksację, ćwiczenia oddechowe oraz "
            "trening fonacji."
        ),
    },
    # ---------------------------------------------------------------- kodowanie
    {
        "key": "icd10_f80",
        "title": "Kodowanie ICD-10: swoiste zaburzenia rozwoju mowy i języka (F80)",
        "category": "icd",
        "audience": "children",
        "icd10": "F80",
        "icd11": "6A01",
        "tags": "ICD-10, F80, F80.0, F80.1, F80.2, F80.3, F80.8, F80.9, kody",
        "text": (
            "ICD-10 grupa F80: F80.0 – swoiste zaburzenia artykulacji mowy (dyslalia, w tym "
            "rotacyzm i sygmatyzm); F80.1 – zaburzenie mowy typu ekspresywnego; F80.2 – zaburzenie "
            "rozumienia mowy (typu receptywnego); F80.3 – nabyta afazja z padaczką (zespół "
            "Landaua-Kleffnera); F80.8 – inne rozwojowe zaburzenia mowy i języka; F80.9 – "
            "nieokreślone. W ICD-11 odpowiada im blok 6A01: 6A01.0 – rozwojowe zaburzenie "
            "wymowy głosek, 6A01.1 – rozwojowe zaburzenie płynności mowy, 6A01.2 – rozwojowe "
            "zaburzenie językowe z upośledzeniem mowy ekspresywnej i receptywnej, 6A01.3 – "
            "zaburzenie z upośledzeniem głównie językowej pragmatyki."
        ),
    },
    {
        "key": "icd10_neuro_fluency",
        "title": "Kodowanie ICD-10: afazja, dyzartria, dysfonia, zaburzenia płynności",
        "category": "icd",
        "audience": "adults",
        "icd10": "R47",
        "icd11": "6A01.1",
        "tags": "ICD-10, R47.0, R47.1, R47.8, R49.0, F98.5, F98.6, I69.3, kody afazja dyzartria",
        "text": (
            "Kody ICD-10 często używane w logopedii dorosłych: R47.0 – dysfazja i afazja; R47.1 – "
            "dyzartria i anartria; R47.8 – inne zaburzenia mowy; R49.0 – dysfonia; R49.1 – afonia; "
            "F98.5 – jąkanie; F98.6 – mowa bezładna; I69.3 – następstwa zawału mózgu (jako kod "
            "dodatkowy przy afazji poudarowej). W ICD-11 jąkanie i mowa bezładna mieszczą się w "
            "6A01.1 (rozwojowe zaburzenie płynności mowy). Przy kodowaniu należy wskazać przyczynę "
            "podstawową (np. udar, choroba Parkinsona) oraz zweryfikować kod w aktualnej wersji "
            "klasyfikacji."
        ),
    },
    # ---------------------------------------------------------------- diagnostyka
    {
        "key": "normy_rozwoju_mowy",
        "title": "Normy rozwoju mowy i wymowy głosek u dzieci",
        "category": "diagnostics",
        "audience": "children",
        "icd10": "",
        "icd11": "",
        "tags": "normy, rozwój mowy, etapy, głoski, wiek, kamienie milowe",
        "text": (
            "Orientacyjne etapy: 0–12 mies. – okres melodii i gaworzenia, pierwsze słowa ok. 12. "
            "miesiąca; 12–24 mies. – okres wyrazu, ok. 24. miesiąca zdania dwuwyrazowe; 2–3 lata – "
            "okres zdania, słownik ok. 200–1000 wyrazów; 3–7 lat – okres swoistej mowy dziecięcej. "
            "Kolejność nabywania głosek: samogłoski i p, b, m, t, d, n, k, g, f, w, ł, l, j, h; "
            "następnie ś, ź, ć, dź (3–4 r.ż.), s, z, c, dz (4–5 r.ż.), sz, ż, cz, dż (5–6 r.ż.), "
            "a na końcu r (do 5–6 r.ż.). Są to normy orientacyjne – indywidualne tempo bywa różne."
        ),
    },
    {
        "key": "kiedy_kierowac",
        "title": "Kiedy skierować pacjenta do innego specjalisty",
        "category": "diagnostics",
        "audience": "all",
        "icd10": "",
        "icd11": "",
        "tags": "skierowanie, laryngolog, foniatra, neurolog, audiolog, psycholog, czerwone flagi",
        "text": (
            "Skierowanie do audiologa/laryngologa: podejrzenie niedosłuchu, nawracające zapalenia "
            "ucha, brak reakcji na dźwięki. Do foniatry: chrypka trwająca ponad 3–4 tygodnie, "
            "nagła zmiana głosu, zaburzenia połykania. Do neurologa: nagłe zaburzenia mowy, "
            "regres umiejętności językowych, asymetria twarzy, objawy ogniskowe (pilnie – "
            "podejrzenie udaru). Do psychologa/psychiatry: podejrzenie zaburzeń ze spektrum "
            "autyzmu, mutyzmu wybiórczego, nasilone objawy lękowe. Do ortodonty: wady zgryzu "
            "wpływające na artykulację; do chirurga: ankyloglosja z ograniczeniem ruchomości języka."
        ),
    },
    # ---------------------------------------------------------------- techniki: dzieci
    {
        "key": "terapia_r",
        "title": "Terapia rotacyzmu – wywoływanie głoski r",
        "category": "technique",
        "audience": "children",
        "icd10": "F80.0",
        "icd11": "6A01.0",
        "tags": "rotacyzm, r, pionizacja języka, wibracja, ćwiczenia, wywoływanie, koniki, malarz",
        "text": (
            "Etapy: (1) ćwiczenia sprawności języka i pionizacji – kląskanie („koniki”), „malarz” "
            "(przesuwanie czubka języka po podniebieniu), „grzybek” (przyssanie języka do "
            "podniebienia), unoszenie języka za górne zęby; (2) ćwiczenia oddechowe i "
            "wydmuchiwanie strumienia powietrza wzdłuż języka; (3) wywołanie głoski – np. z "
            "wielokrotnie powtarzanego „t-d” lub „dyrygent” przy wysoko uniesionym języku, z "
            "podparciem czubka języka szpatułką; (4) utrwalanie r w izolacji, sylabach (ra, ro, re), "
            "wyrazach w nagłosie, śródgłosie i wygłosie, zdaniach i mowie spontanicznej. Ćwiczenia "
            "wykonuje się codziennie po kilka minut z kontrolą lustra."
        ),
    },
    {
        "key": "cwiczenia_narzadow_artykulacyjnych",
        "title": "Ćwiczenia narządów artykulacyjnych i oddechowe u dzieci",
        "category": "technique",
        "audience": "children",
        "icd10": "F80.0",
        "icd11": "6A01.0",
        "tags": "gimnastyka artykulacyjna, warga, język, oddech, dmuchanie, masaż logopedyczny, lustro",
        "text": (
            "Gimnastyka buzi i języka: ćwiczenia warg (uśmiech, ryjek, parskanie), języka (wysuwanie, "
            "unoszenie, kółka po wargach, „kotek pije mleko”, „język do nosa”) i żuchwy. Ćwiczenia "
            "oddechowe: dmuchanie na piórka, waciki, bańki mydlane, wydmuchiwanie piłeczki przez "
            "słomkę, nauka oddechu przeponowego. Zabawy prowadzi się krótko (5–10 minut), w formie "
            "zabawy, przed lustrem. Masaż logopedyczny stosuje się przy obniżonym napięciu mięśni "
            "artykulacyjnych."
        ),
    },
    {
        "key": "lidcombe",
        "title": "Program Lidcombe – terapia jąkania u dzieci w wieku przedszkolnym",
        "category": "technique",
        "audience": "children",
        "icd10": "F98.5",
        "icd11": "6A01.1",
        "tags": "Lidcombe, jąkanie, dzieci, rodzice, werbalna kontyngencja, przedszkole",
        "text": (
            "Program Lidcombe to behawioralna terapia jąkania dla dzieci do ok. 6. roku życia "
            "prowadzona przez rodziców w domu pod cotygodniowym nadzorem logopedy. Opiera się na "
            "werbalnej kontyngencji: pochwały za płynną mowę („Ładnie powiedziałeś, bez zacięcia”), "
            "prośby o samoocenę oraz łagodna korekta pojedynczych zająknięć. Sesje domowe trwają "
            "kilkanaście minut dziennie, a nasilenie ocenia się skalą 1–10 (severity rating). Faza 1 "
            "trwa do uzyskania minimalnego nasilenia, faza 2 to utrzymanie efektów z rzadszymi "
            "kontrolami."
        ),
    },
    {
        "key": "metoda_krakowska",
        "title": "Metoda Krakowska w terapii opóźnionego rozwoju mowy i afazji dziecięcej",
        "category": "technique",
        "audience": "children",
        "icd10": "F80.1",
        "icd11": "6A01.2",
        "tags": "Metoda Krakowska, Cieszyńska, alalia, afazja dziecięca, czytanie symultaniczne, ORM",
        "text": (
            "Metoda Krakowska (Jagoda Cieszyńska) to system terapii rozwoju mowy oparty na "
            "kolejności rozwoju: ćwiczenia percepcji wzrokowej i słuchowej, naśladowania, "
            "ćwiczenia funkcji poznawczych, a następnie nauka czytania symultanicznego – całych "
            "wyrazów prezentowanych na kartonikach, kojarzonych z obrazkiem – jako drogi do "
            "wywołania mowy czynnej. Stosowana m.in. u dzieci z opóźnionym rozwojem mowy, "
            "alalią, afazją dziecięcą i zaburzeniami ze spektrum autyzmu."
        ),
    },
    {
        "key": "swiadomosc_fonologiczna",
        "title": "Trening słuchu fonemowego i świadomości fonologicznej",
        "category": "technique",
        "audience": "children",
        "icd10": "F80.0",
        "icd11": "6A01.0",
        "tags": "słuch fonemowy, świadomość fonologiczna, rymy, sylaby, różnicowanie głosek, dysleksja",
        "text": (
            "Ćwiczenia rozwijające słuch fonemowy: rozpoznawanie dźwięków otoczenia, "
            "różnicowanie par minimalnych (kasa–kasza, ser–szer), rozpoznawanie rymów, analiza i "
            "synteza sylabowa oraz głoskowa, wyszukiwanie głosek w nagłosie, śródgłosie i wygłosie, "
            "zabawy „Jaka to głoska?”. Trening prowadzi się przed i równolegle z korekcją "
            "artykulacji, ponieważ dziecko musi różnicować własną wymowę od wzorca."
        ),
    },
    # ---------------------------------------------------------------- techniki: dorośli
    {
        "key": "mit",
        "title": "Melodyczna terapia intonacyjna (MIT) w afazji Broca",
        "category": "technique",
        "audience": "adults",
        "icd10": "R47.0",
        "icd11": "",
        "tags": "MIT, afazja Broca, intonacja, rytm, powtarzanie, udar, terapia",
        "text": (
            "MIT (Melodic Intonation Therapy) jest stosowana u pacjentów z afazją niepłynną, "
            "dobrym rozumieniem i ograniczonym powtarzaniem. Terapeuta i pacjent intonują krótkie, "
            "użyteczne frazy („Dzień dobry”, „Chcę pić”) z dwutonową melodią i rytmicznym "
            "stukaniem lewą ręką pacjenta w rytm sylab. Stopniowo zwiększa się długość fraz, "
            "usuwa wsparcie melodyczne i przechodzi do mowy z normalną prozodią. Intensywny "
            "protokół to zwykle sesje kilka razy w tygodniu przez kilka tygodni."
        ),
    },
    {
        "key": "cilt",
        "title": "Terapia ograniczania (CILT) i analiza cech semantycznych (SFA) w afazji",
        "category": "technique",
        "audience": "adults",
        "icd10": "R47.0",
        "icd11": "",
        "tags": "CILT, SFA, anomia, afazja, intensywna terapia, nazywanie, PACE",
        "text": (
            "Constraint-Induced Language Therapy (CILT) to intensywna terapia grupowa w małych "
            "grupach, w której komunikacja odbywa się wyłącznie werbalnie (bez gestów i pisania), "
            "zwykle kilka godzin dziennie przez ok. 2 tygodnie, w formie gier językowych. Semantic "
            "Feature Analysis (SFA) poprawia nazywanie: pacjent nazywa obraz, a następnie podaje "
            "cechy semantyczne (grupa, użycie, właściwości, miejsce, skojarzenia). Metodę PACE "
            "stosuje się do treningu komunikacji pragmatycznej – wymiany informacji z użyciem "
            "dowolnych kanałów, w tym gestu i rysunku."
        ),
    },
    {
        "key": "lsvt_loud",
        "title": "LSVT LOUD – terapia głosu i dyzartrii w chorobie Parkinsona",
        "category": "technique",
        "audience": "adults",
        "icd10": "R47.1",
        "icd11": "",
        "tags": "LSVT, LSVT LOUD, Parkinson, dyzartria hipokinetyczna, głośność, intensywna terapia",
        "text": (
            "LSVT LOUD to program intensywnej terapii zaburzeń głosu i mowy w chorobie Parkinsona, "
            "prowadzony przez certyfikowanego terapeutę: 16 sesji po 60 minut, 4 razy w tygodniu "
            "przez 4 tygodnie, z codziennymi ćwiczeniami domowymi. Głównym celem jest zwiększenie "
            "głośności i wysiłku fonacyjnego („Mów głośno!”) przy kalibracji poczucia własnego "
            "głosu. Ćwiczenia: przedłużone „aaa”, glissanda wysokości tonu, głośne czytanie fraz "
            "funkcjonalnych oraz przenoszenie do codziennej komunikacji."
        ),
    },
    {
        "key": "terapia_dyzartrii",
        "title": "Terapia dyzartrii – oddech, fonacja, artykulacja i tempo",
        "category": "technique",
        "audience": "adults",
        "icd10": "R47.1",
        "icd11": "",
        "tags": "dyzartria, ćwiczenia oddechowe, tempo mowy, artykulacja, wspomagająca komunikacja, AAC",
        "text": (
            "Program terapii dyzartrii zależy od typu i nasilenia: poprawa postawy i oddechu "
            "(oddech przeponowy, kontrola wydechu), trening fonacji (długość, głośność), ćwiczenia "
            "siły i zakresu ruchu warg, języka i żuchwy (przy objawach wiotkich – wzmacniające; "
            "przy spastycznych – rozluźniające), regulacja tempa (metronom, mówienie z pauzami), "
            "strategie kompensacyjne (zwolnienie tempa, zwiększenie wyrazistości, krótsze frazy). "
            "Przy ciężkiej dyzartrii wdraża się wspomagającą i alternatywną komunikację (AAC)."
        ),
    },
    {
        "key": "terapia_jakania_doroslych",
        "title": "Terapia jąkania u młodzieży i dorosłych: fluency shaping i stuttering modification",
        "category": "technique",
        "audience": "adults",
        "icd10": "F98.5",
        "icd11": "6A01.1",
        "tags": "jąkanie, dorośli, fluency shaping, Van Riper, modyfikacja jąkania, łagodny start, lęk",
        "text": (
            "Fluency shaping uczy nowego wzorca mówienia: zwolnione tempo, łagodny początek "
            "fonacji (easy onset), ciągła fonacja, lekkie kontakty artykulacyjne i kontrola "
            "oddechu, z przeniesieniem do codziennych sytuacji. Stuttering modification (Van "
            "Riper) redukuje napięcie i unikanie: identyfikacja zająknięć, desensytyzacja, a "
            "następnie techniki modyfikacji – anulowanie (cancellation), wyjście (pull-out) i "
            "przygotowanie (preparatory set). Nowoczesne podejścia łączą obie strategie z "
            "elementami terapii poznawczo-behawioralnej wobec lęku społecznego."
        ),
    },
    {
        "key": "vocal_function_exercises",
        "title": "Ćwiczenia funkcji głosu (Vocal Function Exercises, Stemple)",
        "category": "technique",
        "audience": "adults",
        "icd10": "R49.0",
        "icd11": "",
        "tags": "dysfonia, VFE, Stemple, ćwiczenia głosu, higiena głosu, glissando, nauczyciele",
        "text": (
            "Vocal Function Exercises to program ćwiczeń dla dysfonii czynnościowej: (1) rozgrzewka "
            "– możliwie długie przedłużanie samogłoski /i/ na dźwięku F; (2) rozciąganie – "
            "glissando w górę na /o/; (3) skracanie – glissando w dół na /o/; (4) ćwiczenia mocy – "
            "przedłużanie /o/ na kolejnych dźwiękach C, D, E, F, G. Ćwiczenia wykonuje się cicho, "
            "zwykle dwa razy dziennie po dwa powtórzenia, przez kilka tygodni. Uzupełnieniem jest "
            "edukacja w zakresie higieny głosu: nawodnienie, unikanie krzyku i chrząkania, "
            "właściwa emisja."
        ),
    },
]
