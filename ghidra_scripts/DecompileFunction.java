// Print decompiled C for the function named in the first script argument.
// @category ChipXray
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class DecompileFunction extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String name = getScriptArgs()[0];
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!f.getName().equals(name)) continue;
            DecompileResults r = ifc.decompileFunction(f, 60, monitor);
            println("=== " + name + " @ " + f.getEntryPoint() + " ===\n" + r.getDecompiledFunction().getC());
            return;
        }
        println("NOT FOUND: " + name);
    }
}
