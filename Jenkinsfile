// Pipeline del curso, adaptado a este proyecto.
// Corre en el Jenkins instalado en la EC2 del proyecto (alli estan docker, pip y la CLI de AWS).
pipeline {
  agent any
  environment { IMAGEN = "gtn-app" }
  stages {
    stage('Validar IaC') {
      steps {
        sh 'pip install cfn-lint 2>/dev/null || pip3 install --user cfn-lint'
        sh 'cfn-lint iac/*.yaml || ~/.local/bin/cfn-lint iac/*.yaml'
      }
    }
    stage('Pruebas') {
      // 56 pruebas automaticas; solo necesitan Python y PyYAML
      steps {
        sh 'pip install pyyaml 2>/dev/null || pip3 install --user pyyaml'
        sh 'python3 -m unittest discover -s tests'
      }
    }
    stage('Construir imagen') {
      // El contexto es la raiz del repo: la imagen incluye app/server.py y frontend/index.html
      steps { sh 'docker build -f app/Dockerfile -t $IMAGEN .' }
    }
    stage('Desplegar') {
      steps { sh 'cd app && docker compose up -d --build' }
    }
    stage('Verificar') {
      steps { sh 'sleep 5 && curl -fsS http://localhost/salud' }
    }
  }
  post {
    success { echo 'Despliegue OK: la pagina responde en el puerto 80' }
    failure { echo 'Pipeline fallo: revisar el paso en rojo' }
  }
}
