#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// Writes building.json (ap/docs/schema/building.schema.json) from the open model, in kN and m.
///
/// Columns and beams come from frame design orientation; bays are the areas whose design
/// orientation is Floor, one polygon each. Area loads are summed per load-pattern type:
/// SuperDead and Dead → sdl_kpa, Live/ReduceLive → live_kpa, RoofLive → roof_live_kpa,
/// Snow → snow_kpa. Uniform and uniform-to-frame area loads both count. A load in a direction
/// other than gravity (10, 11) or Global Z (6) is flagged, never dropped silently.
///
/// Slab self-weight (slab_sw_kpa) is the property's own weight per area, before any self-weight
/// multiplier (like beam self-weight, from section mass): thickness × unit weight for slabs; for decks, fill over and between the ribs plus the deck's own unit weight
/// (matches the SW base reaction, see CLAUDE.md). Anything else is flagged, not guessed.
///
/// `combination` carries the template's initial case (1.2D + 0.5L) as factors per load kind, so
/// the Python side builds its increment from the same factors ETABS applies.
///
/// API calls not already used by Quikcolaps.Etabs are marked VERIFY: check them against the CSI
/// API help for the installed version before trusting the output.
/// </summary>
internal static class Export
{
    private static readonly string[] Kinds = { "sdl", "live", "roof_live", "snow" };

    private sealed record Level(string Name, double Z);
    private sealed record StoryRow(string Name, string BottomLevel, string TopLevel, double BottomZ, double TopZ, bool BelowGrade, bool Occupied);
    private sealed record ColumnRow(string Id, string LocationId, double X, double Y, string Story, double BottomZ, double TopZ,
        string Section, bool SpliceAtBottom, bool LandsOnBeam);
    private sealed record BeamRow(string Id, string Level, double Z, double[] I, double[] J, string Section);
    private sealed record BayRow(string Id, string Level, double Z, double[][] Polygon, Dictionary<string, double> Loads, string Property);
    private sealed record LineLoadRow(string BeamId, string Pattern, double WKnPerM);
    private sealed record SectionRow(double MassKgPerM);

    public static int Run(cSapModel sap, string modelPath, string outPath, string templateName)
    {
        var doc = Si.With(sap, () => Build(sap, modelPath, templateName));
        Json.Write(outPath, doc);
        return 0;
    }

    private static object Build(cSapModel sap, string modelPath, string templateName)
    {
        var flags = new List<string>();
        var (levels, stories) = Stories(sap);
        var patternKind = PatternKinds(sap, flags);
        var combination = Combination(sap, templateName, patternKind, flags);
        var slabWeight = new Dictionary<string, double>();

        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");

        var columns = new List<ColumnRow>();
        var beams = new List<BeamRow>();
        var lineLoads = new List<LineLoadRow>();
        var sections = new Dictionary<string, SectionRow>();
        var baseZ = levels.Count > 0 ? levels[0].Z : 0.0;

        foreach (var f in frames)
        {
            string label = "", story = "", i = "", j = "", section = "", auto = "";
            sap.FrameObj.GetLabelFromName(f, ref label, ref story);
            sap.FrameObj.GetSection(f, ref section, ref auto);
            Api.Check(sap.FrameObj.GetPoints(f, ref i, ref j), $"FrameObj.GetPoints {f}");
            var pi = Coord(sap, i); var pj = Coord(sap, j);
            if (!sections.ContainsKey(section)) sections[section] = new SectionRow(MassPerMetre(sap, section, flags));

            if (ColumnStack.IsColumn(sap, f))
            {
                var (lo, hi, loJoint) = pi.Z <= pj.Z ? (pi, pj, i) : (pj, pi, j);
                var lands = lo.Z > baseZ + 1e-3 && !HasColumnBelow(sap, loJoint, f) && !Restrained(sap, loJoint);
                if (lands) flags.Add($"column {f} ({label}@{story}) has no column below and no support at joint {loJoint}");
                columns.Add(new ColumnRow(f, label, lo.X, lo.Y, story, lo.Z, hi.Z, section, false, lands));
            }
            else
            {
                beams.Add(new BeamRow(f, story, (pi.Z + pj.Z) / 2, new[] { pi.X, pi.Y }, new[] { pj.X, pj.Y }, section));
                foreach (var (pattern, w) in FrameLineLoads(sap, f, patternKind, flags))
                    if (patternKind.TryGetValue(pattern, out var kind) && kind == "sdl")
                        lineLoads.Add(new LineLoadRow(f, pattern, w));
            }
        }

        // splice_at_bottom: the section changes from the segment below on the same column line.
        var byLine = columns.GroupBy(c => c.LocationId);
        columns = byLine.SelectMany(g =>
        {
            var seq = g.OrderBy(c => c.BottomZ).ToList();
            return seq.Select((c, k) => k > 0 && seq[k - 1].Section != c.Section ? c with { SpliceAtBottom = true } : c);
        }).ToList();

        var bays = new List<BayRow>();
        n = 0; string[] areas = Array.Empty<string>();
        Api.Check(sap.AreaObj.GetNameList(ref n, ref areas), "AreaObj.GetNameList");
        foreach (var a in areas)
        {
            eAreaDesignOrientation o = default;
            if (sap.AreaObj.GetDesignOrientation(a, ref o) != 0 || o != eAreaDesignOrientation.Floor) continue;
            string label = "", story = "", prop = "";
            sap.AreaObj.GetLabelFromName(a, ref label, ref story);
            sap.AreaObj.GetProperty(a, ref prop);

            int np = 0; string[] pts = Array.Empty<string>();
            Api.Check(sap.AreaObj.GetPoints(a, ref np, ref pts), $"AreaObj.GetPoints {a}");   // VERIFY
            var coords = pts.Take(np).Select(p => Coord(sap, p)).ToList();
            var loads = AreaLoads(sap, a, patternKind, flags);
            if (!slabWeight.TryGetValue(prop, out var sw)) slabWeight[prop] = sw = SlabSelfWeight(sap, prop, flags);
            loads["slab_sw_kpa"] = sw;
            bays.Add(new BayRow(a, story, coords.Average(c => c.Z),
                coords.Select(c => new[] { c.X, c.Y }).ToArray(), loads, prop));
        }

        return new
        {
            meta = new
            {
                name = Path.GetFileNameWithoutExtension(modelPath),
                source = "etabs",
                etabs_file = modelPath,
                units = new { length = "m", force = "kN", pressure = "kPa" },
                material = "steel",
            },
            combination,
            levels,
            stories,
            sections,
            columns,
            beams,
            bays,
            line_loads = lineLoads,
            point_loads = Array.Empty<object>(),
            zones = Array.Empty<object>(),
            flags = flags.Distinct().ToList(),
        };
    }

    /// <summary>Levels bottom to top (Base first) and stories between them. VERIFY GetStories_2.</summary>
    private static (List<Level>, List<StoryRow>) Stories(cSapModel sap)
    {
        double baseElev = 0; int n = 0; string[] names = Array.Empty<string>(); double[] elev = Array.Empty<double>(), height = Array.Empty<double>();
        bool[] master = Array.Empty<bool>(), splice = Array.Empty<bool>(); string[] similar = Array.Empty<string>();
        double[] spliceH = Array.Empty<double>(); int[] color = Array.Empty<int>();
        Api.Check(sap.Story.GetStories_2(ref baseElev, ref n, ref names, ref elev, ref height, ref master, ref similar,
            ref splice, ref spliceH, ref color), "Story.GetStories_2");

        var ordered = Enumerable.Range(0, n).Select(k => (Name: names[k], Z: elev[k]))
            .Where(s => s.Z > baseElev + 1e-6).OrderBy(s => s.Z).ToList();
        var levels = new List<Level> { new("Base", baseElev) };
        levels.AddRange(ordered.Select(s => new Level(s.Name, s.Z)));
        var stories = new List<StoryRow>();
        for (var k = 1; k < levels.Count; k++)
            stories.Add(new StoryRow(levels[k].Name, levels[k - 1].Name, levels[k].Name, levels[k - 1].Z, levels[k].Z, false, true));
        return (levels, stories);
    }

    /// <summary>Load pattern name → sdl | live | roof_live | snow; anything else is ignored and reported.</summary>
    private static Dictionary<string, string> PatternKinds(cSapModel sap, List<string> flags)
    {
        var kinds = new Dictionary<string, string>();
        int n = 0; string[] names = Array.Empty<string>();
        Api.Check(sap.LoadPatterns.GetNameList(ref n, ref names), "LoadPatterns.GetNameList");
        foreach (var p in names)
        {
            eLoadPatternType t = default;
            sap.LoadPatterns.GetLoadType(p, ref t);
            var kind = t.ToString() switch
            {
                "Dead" or "SuperDead" => "sdl",
                "Live" or "ReduceLive" => "live",
                "RoofLive" => "roof_live",
                "Snow" => "snow",
                _ => null
            };
            if (kind is null) flags.Add($"load pattern {p} ({t}) not exported (not dead, live, roof live or snow)");
            else kinds[p] = kind;
        }
        return kinds;
    }


    /// <summary>
    /// The template's initial case as factors: per pattern, and per load kind for the Python side.
    /// self_weight is Σ factor × self-weight multiplier. A kind whose patterns carry different factors
    /// (a pattern missing from the case counts as 0) is left out and flagged; nothing is averaged.
    /// </summary>
    private static object Combination(cSapModel sap, string templateName, Dictionary<string, string> kinds, List<string> flags)
    {
        var template = CaseTemplate.Read(sap, templateName);
        var patterns = new Dictionary<string, double>();
        foreach (var l in CaseLoads.Initial(sap, template.InitialCase))
        {
            if (l.Type != "Load") { flags.Add($"initial case {template.InitialCase} holds {l.Type} {l.Name}; not exported"); continue; }
            patterns[l.Name] = patterns.GetValueOrDefault(l.Name) + l.Scale;
        }

        var factors = new Dictionary<string, double>();
        double selfWeight = 0;
        foreach (var (p, f) in patterns)
        {
            double sw = 0;
            sap.LoadPatterns.GetSelfWTMultiplier(p, ref sw);
            selfWeight += f * sw;
            if (!kinds.ContainsKey(p) && f != 0) flags.Add($"initial case {template.InitialCase} carries {f} × {p}, which is not exported");
        }
        factors["self_weight"] = selfWeight;
        foreach (var kind in Kinds)
        {
            var of = kinds.Where(k => k.Value == kind).Select(k => patterns.GetValueOrDefault(k.Key)).Distinct().ToList();
            if (of.Count == 1) factors[kind] = of[0];
            else if (of.Count > 1) flags.Add($"initial case {template.InitialCase}: {kind} patterns carry different factors ({string.Join(", ", of)}); {kind} factor not exported");
            else factors[kind] = 0;
        }
        return new { initial_case = template.InitialCase, template = template.Name, patterns, factors };
    }

    /// <summary>
    /// Uniform and uniform-to-frame area loads, gravity positive, kPa, keyed sdl_kpa / live_kpa /
    /// roof_live_kpa / snow_kpa. VERIFY GetLoadUniform, GetLoadUniformToFrame.
    /// </summary>
    private static Dictionary<string, double> AreaLoads(cSapModel sap, string area, Dictionary<string, string> kinds, List<string> flags)
    {
        var loads = new Dictionary<string, double> { ["sdl_kpa"] = 0, ["live_kpa"] = 0, ["roof_live_kpa"] = 0, ["snow_kpa"] = 0 };
        void Add(string how, string pattern, string csys, int dir, double value)
        {
            if (!kinds.TryGetValue(pattern, out var kind)) return;   // pattern already flagged in PatternKinds
            var g = Gravity(dir, csys, value);
            if (g is null) flags.Add($"{how} area loads on {pattern} in dir {dir} ({csys}) are not exported");
            else loads[kind + "_kpa"] += g.Value;
        }

        int n = 0; string[] names = Array.Empty<string>(), pats = Array.Empty<string>(), csys = Array.Empty<string>();
        int[] dir = Array.Empty<int>(); double[] val = Array.Empty<double>();
        if (sap.AreaObj.GetLoadUniform(area, ref n, ref names, ref pats, ref csys, ref dir, ref val, eItemType.Objects) == 0)
            for (var k = 0; k < n; k++) Add("uniform", pats[k], csys[k], dir[k], val[k]);

        // −100 with no rows is what an area without uniform-to-frame loads answers (measured); any
        // other failure is flagged rather than read as "no load".
        n = 0; names = Array.Empty<string>(); pats = Array.Empty<string>(); csys = Array.Empty<string>();
        dir = Array.Empty<int>(); val = Array.Empty<double>(); int[] dist = Array.Empty<int>();
        var ret = sap.AreaObj.GetLoadUniformToFrame(area, ref n, ref names, ref pats, ref csys, ref dir, ref val, ref dist, eItemType.Objects);
        if (ret == 0)
            for (var k = 0; k < n; k++) Add("uniform-to-frame", pats[k], csys[k], dir[k], val[k]);
        else if (ret != -100 || n != 0)
            flags.Add($"area {area}: AreaObj.GetLoadUniformToFrame returned {ret}; its uniform-to-frame loads are not exported");
        return loads;
    }

    /// <summary>Distributed frame loads, gravity positive, kN/m, averaged over each load. VERIFY GetLoadDistributed.</summary>
    private static IEnumerable<(string Pattern, double W)> FrameLineLoads(cSapModel sap, string frame, Dictionary<string, string> kinds, List<string> flags)
    {
        int n = 0; string[] names = Array.Empty<string>(), pats = Array.Empty<string>(), csys = Array.Empty<string>();
        int[] myType = Array.Empty<int>(), dir = Array.Empty<int>();
        double[] rd1 = Array.Empty<double>(), rd2 = Array.Empty<double>(), d1 = Array.Empty<double>(), d2 = Array.Empty<double>(),
            v1 = Array.Empty<double>(), v2 = Array.Empty<double>();
        if (sap.FrameObj.GetLoadDistributed(frame, ref n, ref names, ref pats, ref myType, ref csys, ref dir,
                ref rd1, ref rd2, ref d1, ref d2, ref v1, ref v2, eItemType.Objects) != 0) yield break;
        for (var k = 0; k < n; k++)
        {
            if (!kinds.ContainsKey(pats[k])) continue;   // pattern already flagged in PatternKinds
            var g = myType[k] == 1 ? Gravity(dir[k], csys[k], (v1[k] + v2[k]) / 2) : null;   // 1 = force per length
            if (g is null)
                flags.Add($"distributed {(myType[k] == 1 ? "force" : "moment")} loads on {pats[k]} in dir {dir[k]} ({csys[k]}) are not exported");
            else
                yield return (pats[k], g.Value * Math.Abs(rd2[k] - rd1[k]));
        }
    }

    /// <summary>Gravity (10, 11) is positive down; Global Z (6) is positive up; anything else is not handled.</summary>
    private static double? Gravity(int dir, string csys, double value) => dir switch
    {
        10 or 11 => value,
        6 when csys.Equals("Global", StringComparison.OrdinalIgnoreCase) => -value,
        _ => null
    };

    /// <summary>Weight per area of a slab or a deck property; the combination's self_weight factor carries the multiplier.</summary>
    private static double SlabSelfWeight(cSapModel sap, string prop, List<string> flags)
    {
        eSlabType slab = default; eShellType shell = default; string mat = "", notes = "", guid = ""; double t = 0; int color = 0;
        if (sap.PropArea.GetSlab(prop, ref slab, ref shell, ref mat, ref t, ref color, ref notes, ref guid) == 0)   // VERIFY
        {
            if (shell == eShellType.Layered)
            {
                flags.Add($"area property {prop} is a layered shell; its self-weight is not exported (set slab_sw_kpa by hand)");
                return 0;
            }
            if (slab is eSlabType.Ribbed or eSlabType.Waffle)
                flags.Add($"area property {prop} is {slab}: slab_sw_kpa covers the top slab only, not the ribs");
            return t * UnitWeight(sap, mat);
        }

        // Deck: GetSlab answers 1 for a deck property (measured).
        eDeckType deck = default; string fill = "", deckMat = "";
        double tc = 0, hr = 0, wrt = 0, wrb = 0, sr = 0, tShear = 0, deckWeight = 0, dia = 0, hs = 0, fu = 0;
        if (sap.PropArea.GetDeck_1(prop, ref deck, ref fill, ref deckMat, ref tc, ref hr, ref wrt, ref wrb, ref sr, ref tShear,
                ref deckWeight, ref dia, ref hs, ref fu, ref color, ref notes, ref guid) == 0)   // VERIFY
        {
            var w = deck switch
            {
                eDeckType.Filled when sr > 0 => UnitWeight(sap, fill) * (tc + hr * (wrt + wrb) / 2 / sr) + deckWeight,
                eDeckType.Unfilled => deckWeight,
                eDeckType.SolidSlab => UnitWeight(sap, fill) * tc,
                _ => double.NaN
            };
            if (!double.IsNaN(w)) return w;
        }
        flags.Add($"area property {prop} is neither a slab nor a deck read here; its self-weight is not exported (set slab_sw_kpa by hand)");
        return 0;
    }

    private static double UnitWeight(cSapModel sap, string material)
    {
        double w = 0, m = 0;
        Api.Check(sap.PropMaterial.GetWeightAndMass(material, ref w, ref m, 0), $"PropMaterial.GetWeightAndMass {material}");
        return w;
    }

    private static double MassPerMetre(cSapModel sap, string section, List<string> flags)
    {
        double area = 0, x = 0, w = 0, m = 0; string mat = "";
        if (sap.PropFrame.GetSectProps(section, ref area, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x) != 0)
        {
            flags.Add($"section {section}: no properties");
            return 0;
        }
        sap.PropFrame.GetMaterial(section, ref mat);
        sap.PropMaterial.GetWeightAndMass(mat, ref w, ref m, 0);
        return area * w / 9.81e-3; // kN/m → kg/m
    }

    private static bool HasColumnBelow(cSapModel sap, string joint, string self)
    {
        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>(); int[] at = Array.Empty<int>();
        sap.PointObj.GetConnectivity(joint, ref n, ref types, ref names, ref at);
        for (var k = 0; k < n; k++)
        {
            if (types[k] != ObjectType.Frame || names[k] == self || !ColumnStack.IsColumn(sap, names[k])) continue;
            string i = "", j = "";
            sap.FrameObj.GetPoints(names[k], ref i, ref j);
            var upper = Coord(sap, i).Z >= Coord(sap, j).Z ? i : j;
            if (upper == joint) return true;
        }
        return false;
    }

    private static bool Restrained(cSapModel sap, string joint)
    {
        bool[] r = new bool[6];
        return sap.PointObj.GetRestraint(joint, ref r) == 0 && r.Any(x => x);
    }

    internal static (double X, double Y, double Z) Coord(cSapModel sap, string point)
    {
        double x = 0, y = 0, z = 0;
        Api.Check(sap.PointObj.GetCoordCartesian(point, ref x, ref y, ref z, "Global"), $"PointObj.GetCoordCartesian {point}");
        return (x, y, z);
    }
}
#endif
