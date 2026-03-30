plugins {
    application
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.kotlin.plugin.serialization")
}

java {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
}

application {
    mainClass.set("com.smartcard.signer.PiMainKt")
}

dependencies {
    implementation(project(":satochip-lib"))

    implementation("fr.acinq.bitcoin:bitcoin-kmp-jvm:0.21.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    implementation("org.web3j:crypto:4.9.8") {
        exclude(group = "org.bouncycastle", module = "bcprov-jdk18on")
        exclude(group = "org.bouncycastle", module = "bcpkix-jdk18on")
        exclude(group = "org.bouncycastle", module = "bcutil-jdk18on")
    }

    implementation("com.google.zxing:core:3.5.3")
    implementation("com.google.zxing:javase:3.5.3")
}

val releaseBundleDir = layout.buildDirectory.dir("release/offline-signer")

tasks.register<Sync>("assembleReleaseBundle") {
    dependsOn(tasks.installDist)
    from(layout.buildDirectory.dir("install/pi-signer"))
    into(releaseBundleDir)
}
