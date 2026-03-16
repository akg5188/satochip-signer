# Project-specific R8/ProGuard rules.
# Keep this intentionally minimal; dependency AARs already ship consumer rules.

# Keep runtime-visible annotations used by serializers and SDK metadata.
-keepattributes RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,AnnotationDefault,Signature,InnerClasses,EnclosingMethod

# Some transitive SDKs reference java.util.logging types that are not part of
# the Android runtime surface used here; suppress to keep release minification working.
-dontwarn java.util.logging.Level
-dontwarn java.util.logging.Logger
