import java.nio.file.Files;
import java.nio.file.Paths;
import jdk.internal.org.objectweb.asm.ClassReader;
import jdk.internal.org.objectweb.asm.ClassWriter;
import jdk.internal.org.objectweb.asm.Opcodes;
import jdk.internal.org.objectweb.asm.tree.*;

/** Keep the separate PC service's existing maze/admin methods byte-for-byte in meaning. */
public final class GraftLocalTitle implements Opcodes {
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("PC class, tested donor class, output");
        ClassNode old=new ClassNode(),donor=new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(old,0);
        new ClassReader(Files.readAllBytes(Paths.get(args[1]))).accept(donor,0);
        if(!old.name.equals("com/codex/witchweapon/LocalSave")||!old.name.equals(donor.name))
            throw new IllegalArgumentException("Wrong class");
        MethodNode selected=null,respond=null;
        for(Object raw:old.methods){MethodNode method=(MethodNode)raw;
            if(method.name.equals("changeTitle"))throw new IllegalArgumentException("Title method already present");
            if(method.name.equals("respond")&&method.desc.contains("WeaponFurnace"))respond=method;
        }
        for(Object raw:donor.methods){MethodNode method=(MethodNode)raw;
            if(method.name.equals("changeTitle"))selected=method;
        }
        if(selected==null||respond==null)throw new IllegalArgumentException("Missing methods");
        old.methods.add(selected);
        AbstractInsnNode headBox=null;
        for(AbstractInsnNode node=respond.instructions.getFirst();node!=null;node=node.getNext())
            if(node instanceof LdcInsnNode&&"curHeadBox".equals(((LdcInsnNode)node).cst)){
                if(headBox!=null)throw new IllegalArgumentException("Ambiguous role title insertion");
                headBox=node;
            }
        if(headBox==null)throw new IllegalArgumentException("Missing head selection");
        int receiver=-1;
        for(AbstractInsnNode node=headBox.getPrevious();node!=null;node=node.getPrevious())
            if(node instanceof IntInsnNode&&((IntInsnNode)node).operand==118){
                AbstractInsnNode load=node.getPrevious();
                while(load.getOpcode()<0)load=load.getPrevious();
                if(!(load instanceof VarInsnNode)||load.getOpcode()!=ALOAD)
                    throw new IllegalArgumentException("Role receiver changed");
                receiver=((VarInsnNode)load).var;break;
            }
        AbstractInsnNode end=headBox;
        while(end!=null&&end.getOpcode()!=POP)end=end.getNext();
        if(receiver<1||end==null)throw new IllegalArgumentException("Role chain changed");
        InsnList code=new InsnList();
        code.add(new VarInsnNode(ALOAD,receiver));
        code.add(new IntInsnNode(SIPUSH,123));
        code.add(new VarInsnNode(ALOAD,0));
        code.add(new LdcInsnNode("curTitle"));
        code.add(new InsnNode(ICONST_0));
        code.add(new MethodInsnNode(INVOKESPECIAL,old.name,"selectedCosmetic","(Ljava/lang/String;I)I",false));
        code.add(new InsnNode(I2L));
        code.add(new MethodInsnNode(INVOKEVIRTUAL,"com/codex/witchweapon/ProtoWire","set",
            "(IJ)Lcom/codex/witchweapon/ProtoWire;",false));
        code.add(new InsnNode(POP));
        respond.instructions.insert(end,code);
        ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);
        old.accept(writer);
        Files.write(Paths.get(args[2]),writer.toByteArray());
        System.out.println("LOCAL_TITLE_GRAFTED: one method and selected-title field");
    }
}
