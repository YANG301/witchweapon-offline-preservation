import jdk.internal.org.objectweb.asm.*;
import jdk.internal.org.objectweb.asm.tree.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import java.io.*;

/** Patch a copy of the PC jar, preserving its admin and local startup methods. */
public final class MazePcCandidatePatcher {
    private static final String PREFIX="com/codex/witchweapon/";
    private static ClassNode read(byte[] bytes){
        ClassNode node=new ClassNode(Opcodes.ASM5);new ClassReader(bytes).accept(node,0);return node;
    }
    private static byte[] write(byte[] original,ClassNode node){
        ClassWriter writer=new ClassWriter(new ClassReader(original),ClassWriter.COMPUTE_FRAMES|ClassWriter.COMPUTE_MAXS){
            protected String getCommonSuperClass(String one,String two){
                try{
                    ClassLoader loader=MazePcCandidatePatcher.class.getClassLoader();
                    Class<?> a=Class.forName(one.replace('/','.'),false,loader),b=Class.forName(two.replace('/','.'),false,loader);
                    if(a.isAssignableFrom(b))return one;if(b.isAssignableFrom(a))return two;
                    if(a.isInterface() || b.isInterface())return "java/lang/Object";
                    do{a=a.getSuperclass();}while(!a.isAssignableFrom(b));return a.getName().replace('.','/');
                }catch(Exception ex){throw new IllegalStateException("Missing PC frame type "+one+" / "+two,ex);}
            }
        };
        node.accept(writer);return writer.toByteArray();
    }
    private static MethodNode method(ClassNode node,String name,String desc){
        for(Object raw:node.methods){MethodNode m=(MethodNode)raw;if(m.name.equals(name) && (desc==null || m.desc.equals(desc)))return m;}
        throw new IllegalStateException("Missing method "+name+desc);
    }
    private static AbstractInsnNode realNext(AbstractInsnNode node){
        do{node=node.getNext();}while(node!=null && node.getOpcode()<0);return node;
    }
    private static AbstractInsnNode[] mazeBlock(MethodNode method){
        AbstractInsnNode call=null,previousRespond=null;
        for(AbstractInsnNode n=method.instructions.getFirst();n!=null;n=n.getNext())if(n instanceof MethodInsnNode){
            MethodInsnNode m=(MethodInsnNode)n;
            if(m.owner.equals(PREFIX+"LocalSave") && m.name.equals("respond"))previousRespond=n;
            if(m.owner.equals(PREFIX+"LocalSave") && m.name.equals("mazeJson")){call=n;break;}
        }
        if(call==null || previousRespond==null)throw new IllegalStateException("Missing unique maze JSON block");
        AbstractInsnNode store=realNext(previousRespond),start=realNext(store),end=realNext(call);
        if(store.getOpcode()!=Opcodes.ASTORE || start.getOpcode()!=Opcodes.ILOAD || end.getOpcode()!=Opcodes.ASTORE)
            throw new IllegalStateException("Maze JSON block structure changed");
        return new AbstractInsnNode[]{start,end};
    }
    private static void addJsonDelegate(MethodNode target,MethodNode online){
        AbstractInsnNode[] range=mazeBlock(online);
        AbstractInsnNode before=null;
        for(AbstractInsnNode n=target.instructions.getFirst();n!=null;n=n.getNext())if(n instanceof MethodInsnNode){
            MethodInsnNode m=(MethodInsnNode)n;
            if(m.owner.equals(PREFIX+"LocalSave") && m.name.equals("respond"))before=realNext(realNext(n));
        }
        if(before==null || before.getOpcode()!=Opcodes.NEW)throw new IllegalStateException("PC reply tail differs");
        Map<LabelNode,LabelNode> labels=new HashMap<LabelNode,LabelNode>();
        for(AbstractInsnNode n=online.instructions.getFirst();n!=null;n=n.getNext())if(n instanceof LabelNode)
            labels.put((LabelNode)n,new LabelNode());
        Set<AbstractInsnNode> inside=new HashSet<AbstractInsnNode>();
        for(AbstractInsnNode n=range[0];;n=n.getNext()){inside.add(n);if(n==range[1])break;}
        Set<LabelNode> external=new HashSet<LabelNode>();
        InsnList block=new InsnList();
        for(AbstractInsnNode n=range[0];;n=n.getNext()){
            if(n instanceof JumpInsnNode && !inside.contains(((JumpInsnNode)n).label))external.add(((JumpInsnNode)n).label);
            if(!(n instanceof FrameNode) && !(n instanceof LineNumberNode))block.add(n.clone(labels));
            if(n==range[1])break;
        }
        if(external.size()!=1)throw new IllegalStateException("Unexpected maze delegate exit targets");
        block.add(labels.get(external.iterator().next()));target.instructions.insertBefore(before,block);
    }
    private static void removeMazeBlock(MethodNode target){
        AbstractInsnNode[] range=mazeBlock(target);
        AbstractInsnNode next;
        for(AbstractInsnNode n=range[0];;n=next){next=n.getNext();target.instructions.remove(n);if(n==range[1])break;}
    }
    private static String fingerprint(MethodNode method){
        Map<LabelNode,Integer> labels=new HashMap<LabelNode,Integer>();int count=0;
        for(AbstractInsnNode n=method.instructions.getFirst();n!=null;n=n.getNext()){
            if(n instanceof LabelNode)labels.put((LabelNode)n,count);if(n.getOpcode()>=0)count++;
        }
        StringBuilder out=new StringBuilder();
        out.append(method.access).append('|').append(method.name).append(method.desc).append('|').append(method.exceptions).append('\n');
        for(AbstractInsnNode n=method.instructions.getFirst();n!=null;n=n.getNext()){
            if(n.getOpcode()<0)continue;out.append(n.getOpcode()).append(':');
            if(n instanceof VarInsnNode)out.append(((VarInsnNode)n).var);
            else if(n instanceof IntInsnNode)out.append(((IntInsnNode)n).operand);
            else if(n instanceof TypeInsnNode)out.append(((TypeInsnNode)n).desc);
            else if(n instanceof FieldInsnNode){FieldInsnNode f=(FieldInsnNode)n;out.append(f.owner).append(f.name).append(f.desc);}
            else if(n instanceof MethodInsnNode){MethodInsnNode m=(MethodInsnNode)n;out.append(m.owner).append(m.name).append(m.desc).append(m.itf);}
            else if(n instanceof InvokeDynamicInsnNode){InvokeDynamicInsnNode m=(InvokeDynamicInsnNode)n;out.append(m.name).append(m.desc).append(m.bsm).append(Arrays.toString(m.bsmArgs));}
            else if(n instanceof JumpInsnNode)out.append(labels.get(((JumpInsnNode)n).label));
            else if(n instanceof LdcInsnNode)out.append(((LdcInsnNode)n).cst);
            else if(n instanceof IincInsnNode){IincInsnNode i=(IincInsnNode)n;out.append(i.var).append(',').append(i.incr);}
            else if(n instanceof TableSwitchInsnNode){TableSwitchInsnNode s=(TableSwitchInsnNode)n;out.append(s.min).append(',').append(s.max).append(',').append(labels.get(s.dflt));for(Object l:s.labels)out.append(',').append(labels.get(l));}
            else if(n instanceof LookupSwitchInsnNode){LookupSwitchInsnNode s=(LookupSwitchInsnNode)n;out.append(s.keys).append(',').append(labels.get(s.dflt));for(Object l:s.labels)out.append(',').append(labels.get(l));}
            else if(n instanceof MultiANewArrayInsnNode){MultiANewArrayInsnNode a=(MultiANewArrayInsnNode)n;out.append(a.desc).append(a.dims);}
            out.append('\n');
        }
        for(Object raw:method.tryCatchBlocks){TryCatchBlockNode c=(TryCatchBlockNode)raw;
            out.append("catch:").append(labels.get(c.start)).append(',').append(labels.get(c.end)).append(',')
                .append(labels.get(c.handler)).append(',').append(c.type).append('\n');}
        return out.toString();
    }
    private static Map<String,MethodNode> methods(ClassNode node){
        Map<String,MethodNode> out=new HashMap<String,MethodNode>();
        for(Object raw:node.methods){MethodNode m=(MethodNode)raw;out.put(m.name+m.desc,m);}return out;
    }
    private static byte[] load(ZipFile zip,String path)throws Exception{
        InputStream in=zip.getInputStream(zip.getEntry(path));ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;
        try{while((n=in.read(b))!=-1)out.write(b,0,n);}finally{in.close();}return out.toByteArray();
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=3 && args.length!=4)throw new IllegalArgumentException("pc-baseline online-candidate pc-output [method-names]");
        boolean onlyMethods=args.length==4;
        Map<String,byte[]> replacement=new HashMap<String,byte[]>();Set<String> changedMethods=new TreeSet<String>();
        try(ZipFile pc=new ZipFile(args[0]);ZipFile online=new ZipFile(args[1])){
            String path=PREFIX+"LocalSave.class";byte[] original=load(pc,path);ClassNode target=read(original),source=read(load(online,path));
            Set<String> names=onlyMethods?new HashSet<String>(Arrays.asList(args[3].split(","))):
                new HashSet<String>(Arrays.asList("cscInfo","cscCheckpointLoot","cscLoot","cscRole","cscNormalCommit","cscBonusCommit","cscRuleLevel","mazeJson"));
            for(Object raw:source.methods){MethodNode m=(MethodNode)raw;
                if(names.contains(m.name) || !onlyMethods && m.name.equals("respond") && m.desc.contains("WeaponFurnace")){
                    for(Iterator it=target.methods.iterator();it.hasNext();){MethodNode old=(MethodNode)it.next();if(old.name.equals(m.name)&&old.desc.equals(m.desc))it.remove();}
                    target.methods.add(m);changedMethods.add(m.name+m.desc);
                }
            }
            replacement.put(path,write(original,target));
            Map<String,MethodNode> prior=methods(read(original)),after=methods(read(replacement.get(path)));
            for(String key:prior.keySet())if(!changedMethods.contains(key) && !fingerprint(prior.get(key)).equals(fingerprint(after.get(key))))
                throw new IllegalStateException("PC non-maze LocalSave method altered: "+key);
            if(!onlyMethods){
                path=PREFIX+"StandaloneServer.class";original=load(pc,path);target=read(original);source=read(load(online,path));
                addJsonDelegate(method(target,"resolve",null),method(source,"resolve",null));replacement.put(path,write(original,target));
                prior=methods(read(original));after=methods(read(replacement.get(path)));
                for(String key:prior.keySet()){
                    if(key.startsWith("resolve("))removeMazeBlock(after.get(key));
                    if(!fingerprint(prior.get(key)).equals(fingerprint(after.get(key))))
                        throw new IllegalStateException("PC StandaloneServer local behavior altered: "+key);
                }
            }
            for(String name:onlyMethods?Arrays.asList("BarrierLabyrinth.class","BarrierLabyrinth$Group.class"):
                Arrays.asList("BarrierLabyrinth.class","BarrierLabyrinth$Group.class","MazeRules.class"))replacement.put(PREFIX+name,load(online,PREFIX+name));
            if(!onlyMethods)replacement.put("maze_rules.json",load(online,"maze_rules.json"));
            Path destination=Paths.get(args[2]);Files.createDirectories(destination.getParent());
            try(ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(destination))){
                Enumeration<? extends ZipEntry> entries=pc.entries();
                while(entries.hasMoreElements()){ZipEntry e=entries.nextElement();String name=e.getName();
                    out.putNextEntry(new ZipEntry(name));out.write(replacement.containsKey(name)?replacement.remove(name):load(pc,name));out.closeEntry();
                }
                for(Map.Entry<String,byte[]> e:replacement.entrySet()){out.putNextEntry(new ZipEntry(e.getKey()));out.write(e.getValue());out.closeEntry();}
            }
            System.out.println("PC_MAZE_METHOD_TRANSPLANT_OK "+changedMethods.size()+" methods; all admin/startup/other instructions unchanged");
        }
    }
}
