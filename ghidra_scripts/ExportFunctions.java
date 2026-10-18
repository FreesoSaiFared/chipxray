// Post-analysis: write every non-external function's decompiled C to <outdir>/<program>.json.
// @category ChipXray
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

public class ExportFunctions extends GhidraScript {
    private static String esc(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        return b.append('"').toString();
    }

    @Override
    protected void run() throws Exception {
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        StringBuilder out = new StringBuilder("[");
        boolean first = true;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.isExternal() || f.isThunk()) continue;
            DecompileResults r = ifc.decompileFunction(f, 60, monitor);
            String c = r.getDecompiledFunction() == null ? "" : r.getDecompiledFunction().getC();
            out.append(first ? "" : ",").append("{\"name\":").append(esc(f.getName()))
               .append(",\"entry\":").append(esc(f.getEntryPoint().toString()))
               .append(",\"c\":").append(esc(c)).append("}");
            first = false;
        }
        out.append("]");
        Files.write(Paths.get(getScriptArgs()[0], currentProgram.getName() + ".json"),
                    out.toString().getBytes(StandardCharsets.UTF_8));
    }
}
