// Pre-analysis: rename defined symbols and memory blocks using a TSV alias file (name<TAB>alias).
// @category ChipXray
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class StripNames extends GhidraScript {
    @Override
    protected void run() throws Exception {
        // DWARF debug info (present in the ESP32 library) would restore every real name after this script.
        setAnalysisOption(currentProgram, "DWARF", "false");
        Map<String, String> alias = new HashMap<>();
        for (String line : Files.readAllLines(Paths.get(getScriptArgs()[0]))) {
            String[] p = line.split("\t");
            if (p.length == 2) alias.put(p[0], p[1]);
        }
        List<Symbol> all = new ArrayList<>();
        currentProgram.getSymbolTable().getAllSymbols(true).forEach(all::add);
        for (Symbol s : all) {
            String a = alias.get(s.getName());
            if (a != null) s.setName(a, SourceType.USER_DEFINED);
        }
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            String[] parts = b.getName().split("\\.", -1);
            for (int i = 0; i < parts.length; i++) parts[i] = alias.getOrDefault(parts[i], parts[i]);
            String n = String.join(".", parts);
            if (!n.equals(b.getName())) b.setName(n);
        }
    }
}
